"""30-minute 15 rps real buy-path run against the owned S7 stack."""
import concurrent.futures
import json
import math
import os
import queue
import re
import secrets
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from analyze_order_stages import parse, summarize  # noqa: E402
from stack_client import PROJECT, CMD, settings, activity, buy, clean, fixture_users, login, sql, call, dc, redis  # noqa: E402

QPS = float(os.getenv("SUSTAINED_QPS", "15"))
DURATION = int(os.getenv("SUSTAINED_SECONDS", "1800"))
REPORT_NAME = os.getenv("T048_REPORT_NAME", "t048-sustained.json")
if QPS <= 0 or DURATION < 60:
    raise SystemExit("SUSTAINED_QPS must be positive; SUSTAINED_SECONDS must be >= 60")
if not re.fullmatch(r"t048-[a-z0-9-]+\.json", REPORT_NAME):
    raise SystemExit("T048_REPORT_NAME must be a simple t048-*.json filename")
TOTAL = math.ceil(QPS * DURATION)
ADMIN = login()
NAME = "T048-sustained-" + uuid.uuid4().hex[:10]
ACTIVITY, SKU = activity(ADMIN, TOTAL, NAME)
USERS = fixture_users(TOTAL)
plans = queue.Queue(maxsize=max(120, math.ceil(QPS * 30)))
producer_error = []
producer_done = threading.Event()
durable_watch_stop = threading.Event()
durable_seen_mono = {}
durable_seen_lock = threading.Lock()
CHALLENGE_KEY = f"seckill:{{{ACTIVITY}:{SKU}}}:challenge:"
DIGEST = "8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92"


def prepare_batch(batch_users):
    epoch = dc("exec", "-T", "redis", "redis-cli", "--raw", "HGET",
               f"seckill:{{{ACTIVITY}:{SKU}}}:ledger", "epoch").strip()
    challenges, keys, proofs = [], [], []
    for user_id, token, _expires in batch_users:
        request_id, challenge_id = str(uuid.uuid4()), str(uuid.uuid4())
        activity_token = challenge_id + "." + secrets.token_hex(32)
        captcha_token = secrets.token_hex(32)
        keys.append(CHALLENGE_KEY + challenge_id)
        proof = {"userId": str(user_id), "activityId": str(ACTIVITY), "skuId": str(SKU),
                 "epoch": epoch, "attempts": 0, "used": True, "requestId": request_id,
                 "captchaDigest": __import__("hashlib").sha256(captcha_token.encode()).hexdigest(),
                 "activityDigest": __import__("hashlib").sha256(activity_token.encode()).hexdigest(),
                 "expiresAtMs": int(time.time() * 1000) + 600000}
        proofs.append(json.dumps(proof, separators=(",", ":")))
        challenges.append({"user": user_id, "token": token, "activity": ACTIVITY,
                           "sku": SKU, "requestId": request_id,
                           "body": {"activityId": ACTIVITY, "skuId": SKU,
                                    "requestId": request_id, "activityToken": activity_token,
                                    "captchaToken": captcha_token}})
    script = ('import json,os,redis,sys; rows=json.load(sys.stdin); '
              'r=redis.Redis.from_url(os.environ["MALL_REDIS_URL"]); p=r.pipeline(); '
              '[p.set(row["key"],row["value"],ex=600) for row in rows]; '
              'p.execute(); print(len(rows))')
    proof_rows = [{"key": key, "value": value} for key, value in zip(keys, proofs)]
    seeded = subprocess.run(
        CMD + ["run", "--rm", "--no-deps", "-T", "migrate", "python", "-c", script],
        input=json.dumps(proof_rows), capture_output=True, text=True, timeout=180)
    assert seeded.returncode == 0 and seeded.stdout.strip() == str(len(proof_rows)), (
        seeded.stdout[-300:], seeded.stderr[-300:], len(proof_rows))

    return challenges


def prepare_forever():
    try:
        # Keep a rolling batch ready so test-only captcha issuance does not
        # throttle the timed buy requests. The test records if it still falls behind.
        for start in range(0, TOTAL, 300):
            batch_users = USERS[start:start + 300]
            batch = prepare_batch(batch_users)
            for plan in batch:
                plans.put(plan)
            print(json.dumps({"stage": "prepared", "plans": min(start + len(batch), TOTAL),
                              "total": TOTAL}, ensure_ascii=False), flush=True)
    except BaseException as error:
        producer_error.append(error)
        print(json.dumps({"stage": "prepare_failed", "error": repr(error)},
                         ensure_ascii=False), flush=True)
    finally:
        producer_done.set()


def quantile(values, pct):
    values = sorted(values)
    if not values:
        return None
    return round(values[min(len(values) - 1, math.ceil(len(values) * pct / 100) - 1)], 3)


def measure_mysql_offset():
    before = time.time() * 1000
    service = float(sql("SELECT CAST(UNIX_TIMESTAMP(NOW(3))*1000 AS UNSIGNED)"))
    after = time.time() * 1000
    return service - (before + after) / 2


def measure_redis_offset():
    before = time.time() * 1000
    value = redis("TIME").splitlines()
    after = time.time() * 1000
    service = int(value[0]) * 1000 + int(value[1]) // 1000
    return service - (before + after) / 2


preparer = threading.Thread(target=prepare_forever, name="captcha-token-preparer", daemon=True)
preparer.start()
if plans.empty():
    deadline = time.monotonic() + 60
    while plans.empty() and not producer_done.is_set() and time.monotonic() < deadline:
        time.sleep(.1)
    if plans.empty():
        if producer_error:
            raise RuntimeError("captcha/token preparation failed") from producer_error[0]
        raise RuntimeError("captcha/token preparation produced no plans within 60 seconds")
run_start_mono = time.monotonic()
responses = []


def send(plan):
    started_at_ms = int(time.time() * 1000)
    started = time.monotonic()
    try:
        status, body = buy(plan)
        code = body.get("code", "ACCEPTED" if status == 202 else "UNKNOWN")
    except OSError:
        status, code = 0, "TRANSPORT_UNKNOWN"
    return {"requestId": plan["requestId"], "status": status, "code": code,
            "startedAtMs": started_at_ms, "startedAtMono": started,
            "latencyMs": (time.monotonic() - started) * 1000}


def watch_durable_orders():
    # Use a same-host monotonic clock because container wall clocks can drift
    # relative to Windows/WSL during a long run. Re-read a 30-second overlap
    # behind the newest order timestamp so result volume stays bounded while
    # still capturing delayed/out-of-order commits.
    newest_created_at_ms = 0
    while not durable_watch_stop.is_set():
        try:
            lower_bound = max(0, newest_created_at_ms - 30000)
            query = ("SELECT r.request_id,o.created_at_ms FROM seckill_requests r JOIN orders o "
                     "ON o.reservation_id=r.reservation_id "
                     f"WHERE r.activity_id={ACTIVITY} AND o.created_at_ms>={lower_bound}")
            rows = sql(query).splitlines()
            now = time.monotonic()
            with durable_seen_lock:
                for line in rows:
                    request_id, created_at_ms = line.split("\t")
                    durable_seen_mono.setdefault(request_id, now)
                    newest_created_at_ms = max(newest_created_at_ms, int(created_at_ms))
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass
        durable_watch_stop.wait(.5)


start_db = sql("SHOW GLOBAL STATUS WHERE Variable_name IN "
               "('Innodb_row_lock_waits','Innodb_row_lock_time','Threads_connected','Threads_running')")
mysql_clock_offset_start = measure_mysql_offset()
redis_clock_offset_start = measure_redis_offset()
container_env = subprocess.check_output(
    ["docker", "inspect", "--format", "{{range .Config.Env}}{{println .}}{{end}}",
     f"{PROJECT}-seckill-1"], text=True)
worker_count = int(next((line.split("=", 1)[1] for line in container_env.splitlines()
                         if line.startswith("MALL_HTTP_WORKERS=")), "8"))
order_env = subprocess.check_output(
    ["docker", "inspect", "--format", "{{range .Config.Env}}{{println .}}{{end}}",
     f"{PROJECT}-order-1"], text=True)
consumer_count = int(next((line.split("=", 1)[1] for line in order_env.splitlines()
                           if line.startswith("MALL_MQ_CONSUMER_THREADS=")), "4"))
max_workers = max(64, math.ceil(QPS * 20))
durable_watcher = threading.Thread(target=watch_durable_orders,
                                   name="durable-order-observer", daemon=True)
durable_watcher.start()
with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
    futures = []
    for index in range(TOTAL):
        target = run_start_mono + index / QPS
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        try:
            plan = plans.get(timeout=60)
        except queue.Empty:
            if producer_error:
                raise RuntimeError("captcha/token preparation failed") from producer_error[0]
            raise RuntimeError(f"captcha/token preparation fell behind at request {index}")
        futures.append(pool.submit(send, plan))
        if producer_error:
            raise producer_error[0]
        if (index + 1) % int(max(1, QPS * 60)) == 0:
            print(json.dumps({"minute": (index + 1) / QPS / 60,
                              "submitted": index + 1, "total": TOTAL,
                              "preparedQueueDepth": plans.qsize()}, ensure_ascii=False), flush=True)
    submitted_duration = time.monotonic() - run_start_mono
    responses = [future.result() for future in futures]
preparer.join(timeout=120)
assert not preparer.is_alive(), "credential producer did not finish"
if producer_error:
    raise producer_error[0]

status_counts = {}
business_counts = {}
for row in responses:
    status_counts[str(row["status"])] = status_counts.get(str(row["status"]), 0) + 1
    business_counts[row["code"]] = business_counts.get(row["code"], 0) + 1
accepted = [row for row in responses if row["status"] == 202]

# Preserve client-side evidence before waiting for asynchronous MQ/MySQL drain.
# A reconciliation timeout must not discard the only copy of HTTP counts and
# request latencies after a 30-minute run.
client_checkpoint = {
    "date": "2026-10-15", "activityName": NAME, "activityId": ACTIVITY,
    "skuId": SKU, "offeredQps": QPS, "durationSeconds": DURATION,
    "cppHttpWorkers": worker_count, "mqConsumerThreads": consumer_count,
    "mqQueueCount": int(os.getenv("MALL_MQ_QUEUE_COUNT", settings.get("MALL_MQ_QUEUE_COUNT", "4"))),
    "submitted": TOTAL, "observedSubmissionSeconds": round(time.monotonic() - run_start_mono, 3),
    "httpStatusCounts": status_counts, "businessCodeCounts": business_counts,
    "accepted": len(accepted),
    "buyApiLatencyMsAcceptedOnly": {f"p{p}": quantile([r["latencyMs"] for r in accepted], p)
                                    for p in (50, 95, 99)},
    "server5xxCount": sum(count for status, count in status_counts.items()
                           if status.isdigit() and int(status) >= 500),
    "requestResults": responses,
    "persistenceAndReconciliation": "pending",
}
checkpoint_path = ROOT / "tests" / "reports" / "wsl" / "t048-sustained-client-checkpoint.json"
checkpoint_tmp = checkpoint_path.with_suffix(".tmp")
checkpoint_tmp.write_text(json.dumps(client_checkpoint, ensure_ascii=False), encoding="utf-8")
checkpoint_tmp.replace(checkpoint_path)

# Wait for every explicitly accepted request to become durable. HTTP 502/504
# responses remain ambiguous and are reconciled by request ID and ledger state.
submitted_by_id = {row["requestId"]: row for row in responses}
accepted_ids = {row["requestId"] for row in accepted}
orders, request_states = {}, {}
stable_reserved_count, stable_samples = None, 0
deadline = time.monotonic() + 300
while time.monotonic() < deadline:
    rows = sql("SELECT r.request_id,r.status,o.id,o.created_at_ms,o.status,r.created_at_ms "
               "FROM seckill_requests r LEFT JOIN orders o ON o.reservation_id=r.reservation_id "
               f"WHERE r.activity_id={ACTIVITY}").splitlines()
    orders, request_states = {}, {}
    for line in rows:
        parts = line.split("\t")
        if len(parts) != 6:
            continue
        request_id, request_state, order_id, created, order_state, reserved_at = parts
        request_states[request_id] = request_state
        if order_id != r"\N":
            orders[request_id] = (int(created), order_state, int(reserved_at))
    reserved = len(request_states)
    stable_samples = stable_samples + 1 if reserved == stable_reserved_count else 0
    stable_reserved_count = reserved
    pending_count = int(redis("HGET", f"seckill:{{{ACTIVITY}:{SKU}}}:ledger", "pendingCount") or 0)
    if (accepted_ids.issubset(orders) and pending_count == 0
            and not any(state == "QUEUED" for state in request_states.values())
            and stable_samples >= 4):
        break
    time.sleep(2)
durable_watch_stop.set()
durable_watcher.join(timeout=10)
assert all(value[1] in {"PENDING_PAYMENT", "CLOSED"} for value in orders.values()), \
    "load run produced an unexpected order state"
checkpoint_data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
with durable_seen_lock:
    seen_snapshot = dict(durable_seen_mono)
checkpoint_data["persistedOrdersAtCheckpoint"] = len(orders)
checkpoint_data["databaseVisibleOrders"] = {
    request_id: {
        "firstSeenAfterRequestMs": round((seen_snapshot[request_id]
                                            - submitted_by_id[request_id]["startedAtMono"]) * 1000, 3),
        "orderStatus": order[1],
    }
    for request_id, order in orders.items()
    if request_id in seen_snapshot and request_id in submitted_by_id
}
checkpoint_data["persistenceAndReconciliation"] = "persisted-order-snapshot-saved; reconciliation-pending"
checkpoint_tmp.write_text(json.dumps(checkpoint_data, ensure_ascii=False), encoding="utf-8")
checkpoint_tmp.replace(checkpoint_path)
reconciliation = clean(activity_id=ACTIVITY, limit=100000, timeout=600)
rows = sql("SELECT r.request_id,r.status,o.id,o.created_at_ms,o.status,r.created_at_ms "
           "FROM seckill_requests r LEFT JOIN orders o ON o.reservation_id=r.reservation_id "
           f"WHERE r.activity_id={ACTIVITY}").splitlines()
orders, request_states = {}, {}
for line in rows:
    parts = line.split("\t")
    if len(parts) != 6:
        continue
    request_id, request_state, order_id, created, order_state, reserved_at = parts
    request_states[request_id] = request_state
    if order_id != r"\N":
        orders[request_id] = (int(created), order_state, int(reserved_at))

mysql_clock_offset_end = measure_mysql_offset()
redis_clock_offset_end = measure_redis_offset()
clock_offset = (mysql_clock_offset_start + mysql_clock_offset_end) / 2
redis_clock_offset = (redis_clock_offset_start + redis_clock_offset_end) / 2
started_by_id = {key: row["startedAtMs"] for key, row in submitted_by_id.items()}
with durable_seen_lock:
    durable_observed = dict(durable_seen_mono)
started_mono_by_id = {key: row["startedAtMono"] for key, row in submitted_by_id.items()}
end_to_end = [(durable_observed[key] - started_mono_by_id[key]) * 1000
              for key in orders if key in started_mono_by_id and key in durable_observed]
request_to_reservation = [value[2] - (started_by_id[key] + redis_clock_offset)
                         for key, value in orders.items() if key in started_by_id]

log_lines = []
for service in ("relay", "order"):
    log_lines.extend(subprocess.check_output(
        ["docker", "logs", "--since", "40m", f"{PROJECT}-{service}-1"],
        text=True, stderr=subprocess.STDOUT).splitlines())
reservation_rows = set(sql(
    f"SELECT reservation_id FROM seckill_requests WHERE activity_id={ACTIVITY}"
).splitlines())
reservation_pattern = re.compile(r"\breservationId=([a-f0-9-]{36})\b")
relevant_lines = []
for line in log_lines:
    if "event=seckill_stage" not in line:
        continue
    match = reservation_pattern.search(line)
    if match and match.group(1) in reservation_rows:
        relevant_lines.append(line)
events, malformed, duplicates = parse(relevant_lines)
stage_summary = summarize(events, malformed, duplicates)
reserved_count = int(sql(f"SELECT COUNT(*) FROM seckill_requests WHERE activity_id={ACTIVITY}"))
telemetry_complete = (stage_summary["reservations"] == reserved_count
                     and stage_summary["stageCounts"].get("relay_publish", 0) == reserved_count
                     and stage_summary["stageCounts"].get("consumer_received", 0) == reserved_count
                     and (stage_summary["stageCounts"].get("committed", 0)
                          + stage_summary["stageCounts"].get("failed", 0)) >= len(orders) * .995
                     and stage_summary["malformedStageLines"] == 0)

buy_p95 = quantile([r["latencyMs"] for r in accepted], 95)
durable_p95 = quantile(end_to_end, 95)
durable_p99 = quantile(end_to_end, 99)
server_5xx = sum(count for status, count in status_counts.items()
                 if status.isdigit() and int(status) >= 500)
server_5xx_rate_pct = server_5xx * 100 / TOTAL
observed_qps = TOTAL / submitted_duration

report = {
    "date": "2026-10-15", "platform": "WSL2 Ubuntu; Docker Desktop Linux engine",
    "mount": "/mnt/e (DrvFs)", "loadGenerator": "Python standard-library HTTP clients on same host as Docker",
    "proofFixture": "One-time, 60-second proof rows are batch-seeded with synthetic tokens and their digests; the real C++ /api/seckill/buy handler validates and consumes each proof. Image rendering, token issuance and account setup are outside the timed window.",
    "activityName": NAME, "activityId": ACTIVITY, "skuId": SKU,
    "cppHttpWorkers": worker_count, "mqConsumerThreads": consumer_count,
    "mqQueueCount": int(os.getenv("MALL_MQ_QUEUE_COUNT", settings.get("MALL_MQ_QUEUE_COUNT", "4"))),
    "offeredQps": QPS, "durationSeconds": DURATION, "submitted": TOTAL,
    "accepted": len(accepted), "persisted": len(orders),
    "observedSubmissionSeconds": round(submitted_duration, 3),
    "httpStatusCounts": status_counts, "businessCodeCounts": business_counts,
    "buyApiLatencyMsAcceptedOnly": {f"p{p}": quantile([r["latencyMs"] for r in accepted], p)
                        for p in (50, 95, 99)},
    "requestToReservationMs": {f"p{p}": quantile(request_to_reservation, p)
                               for p in (50, 95, 99)},
    "requestToDurableOrderMs": {f"p{p}": quantile(end_to_end, p) for p in (50, 95, 99)},
    "requestToDurableMeasurement": "same-host monotonic request start to first DB-visible order; polling interval 500ms",
    "requestToDurableObservedCount": len(end_to_end),
    "mysqlClockOffsetMs": round(clock_offset, 3),
    "redisClockOffsetMs": round(redis_clock_offset, 3),
    "mysqlClockOffsetStartEndMs": [round(mysql_clock_offset_start, 3),
                                   round(mysql_clock_offset_end, 3)],
    "redisClockOffsetStartEndMs": [round(redis_clock_offset_start, 3),
                                   round(redis_clock_offset_end, 3)],
    "stageTelemetry": stage_summary,
    "stageTelemetryComplete": telemetry_complete,
    "reserved": reserved_count,
    "server5xxCount": server_5xx,
    "server5xxRatePercent": round(server_5xx_rate_pct, 4),
    "observedSubmissionQps": round(observed_qps, 3),
    "mysqlStatusBefore": start_db,
    "mysqlStatusAfter": sql("SHOW GLOBAL STATUS WHERE Variable_name IN "
                             "('Innodb_row_lock_waits','Innodb_row_lock_time','Threads_connected','Threads_running')"),
    "reconciliation": {"status": reconciliation["status"],
                        "orders": reconciliation["orders"],
                        "alerts": reconciliation["alerts"]},
    "capacityGate": "evaluated against temporary v0.1; same-host run is not an independent production capacity proof",
    "temporaryGateResults": {
        "offeredRateAtLeastTarget": observed_qps >= QPS * 0.99,
        "eligibleRequestsAcceptedAtLeast99_5Percent": reserved_count / TOTAL >= .995,
        "server5xxAtMost0_1Percent": server_5xx_rate_pct <= .1,
        "acceptedBuyApiP95AtMost500ms": buy_p95 is not None and buy_p95 <= 500,
        "durableOrderP95AtMost3000ms": durable_p95 is not None and durable_p95 <= 3000,
        "durableOrderP99AtMost8000ms": durable_p99 is not None and durable_p99 <= 8000,
        "allReservedOrdersPersisted": reserved_count == len(orders),
        "stageTelemetryComplete": telemetry_complete,
        "inventoryReconciliationClean": reconciliation["status"] == "CLEAN",
    },
}
report["temporaryGateResults"]["passed"] = all(report["temporaryGateResults"].values())
out = ROOT / "tests" / "reports" / "wsl" / REPORT_NAME
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"status": "COMPLETED", "submitted": TOTAL, "persisted": len(orders),
                  "accepted": len(accepted), "server5xxRatePercent": report["server5xxRatePercent"],
                  "gatesPassed": report["temporaryGateResults"]["passed"],
                  "p95DurableMs": report["requestToDurableOrderMs"]["p95"],
                  "reconciliation": reconciliation["status"],
                  "report": str(out.relative_to(ROOT))}, ensure_ascii=False), flush=True)
