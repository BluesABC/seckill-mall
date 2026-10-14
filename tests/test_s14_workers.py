"""Controlled S7 worker-count experiment; never changes/removes test volumes."""
import concurrent.futures
import json
import math
import os
import statistics
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from stack_client import PROJECT, activity, clean, fixture_users, login, prepare, sql, buy


ROOT = Path(__file__).resolve().parents[1]
WORKERS = int(sys.argv[1])
ROUNDS = int(os.environ.get("S14_ROUNDS", "3"))
USERS = int(os.environ.get("S14_USERS", "64"))
if WORKERS not in (8, 16, 24, 32, 48, 64) or not 1 <= ROUNDS <= 5 or USERS != 64:
    raise SystemExit("usage: test_s14_workers.py 8|16|24|32|48|64 (S14_ROUNDS=1..5; S14_USERS fixed at 64)")
container_env = subprocess.check_output(
    ["docker", "inspect", "--format", "{{range .Config.Env}}{{println .}}{{end}}",
     PROJECT + "-seckill-1"], text=True)
configured_workers = next((line.split("=", 1)[1] for line in container_env.splitlines()
                           if line.startswith("MALL_HTTP_WORKERS=")), "8")
if int(configured_workers) != WORKERS:
    raise SystemExit(f"worker experiment mismatch: requested {WORKERS}, container has {configured_workers}")


def quantile(values, percentile):
    values = sorted(values)
    return round(values[min(len(values) - 1, math.ceil(len(values) * percentile / 100) - 1)], 3)


def global_status():
    return sql("SHOW GLOBAL STATUS WHERE Variable_name IN "
               "('Innodb_row_lock_waits','Innodb_row_lock_time','Threads_connected','Threads_running')")


def mysql_clock_offset_ms():
    before = time.time_ns() / 1_000_000
    mysql = float(sql("SELECT CAST(UNIX_TIMESTAMP(NOW(3))*1000 AS UNSIGNED)"))
    after = time.time_ns() / 1_000_000
    return mysql - (before + after) / 2


admin = login()
records = []
resource_samples = []
monitor_stop = threading.Event()


def monitor_resources():
    names = [PROJECT + "-" + service + "-1"
             for service in ("seckill", "relay", "order", "redis", "mysql", "broker")]
    while not monitor_stop.is_set():
        try:
            result = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{json .}}", *names],
                text=True, capture_output=True, timeout=15, check=True)
            resource_samples.append({"atMs": int(time.time() * 1000),
                                     "containers": [json.loads(line) for line in result.stdout.splitlines()]})
        except Exception as error:
            resource_samples.append({"atMs": int(time.time() * 1000), "error": type(error).__name__})
        monitor_stop.wait(1)


monitor_thread = threading.Thread(target=monitor_resources, daemon=True)
monitor_thread.start()
for run in range(1, ROUNDS + 1):
    name = f"S14-W{WORKERS}-R{run}-{uuid.uuid4().hex[:8]}"
    activity_id, sku = activity(admin, USERS, name)
    users = fixture_users(USERS)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        plans = list(pool.map(lambda user: prepare(user, activity_id, sku), users))

    db_before = global_status()
    db_clock_offset = mysql_clock_offset_ms()
    start_wall = int(time.time() * 1000)
    started = time.monotonic()

    def timed_buy(plan):
        start_ms = int(time.time() * 1000)
        start_mono = time.monotonic_ns()
        status, body = buy(plan)
        return {"requestId": plan["requestId"], "startedAtMs": start_ms,
                "startMonoNs": start_mono, "endMonoNs": time.monotonic_ns(),
                "status": status, "code": body.get("code", "ACCEPTED" if status == 202 else "UNKNOWN")}

    with concurrent.futures.ThreadPoolExecutor(max_workers=USERS) as pool:
        responses = list(pool.map(timed_buy, plans))
    ingress_seconds = time.monotonic() - started
    assert all(row["status"] == 202 for row in responses), responses

    deadline = time.monotonic() + 180
    rows = []
    while time.monotonic() < deadline:
        raw = sql(
            "SELECT r.request_id,o.created_at_ms,o.status FROM orders o "
            "JOIN seckill_requests r ON r.reservation_id=o.reservation_id "
            f"WHERE o.activity_id={activity_id} ORDER BY o.created_at_ms")
        rows = [line.split("\t") for line in raw.splitlines() if line]
        if len(rows) == USERS:
            break
        time.sleep(0.25)
    assert len(rows) == USERS, f"only {len(rows)}/{USERS} durable orders"
    by_request = {request: (int(created), status) for request, created, status in rows}
    order_ms = [by_request[r["requestId"]][0] - (r["startedAtMs"] + db_clock_offset)
                for r in responses]
    http_ms = [(r["endMonoNs"] - r["startMonoNs"]) / 1_000_000 for r in responses]
    assert all(status == "PENDING_PAYMENT" for _, status in by_request.values())
    reconciliation = clean()
    db_after = global_status()
    records.append({
        "name": name, "workers": WORKERS, "users": USERS, "concurrency": USERS,
        "ingressSeconds": round(ingress_seconds, 3),
        "acceptedQps": round(USERS / ingress_seconds, 3),
        "httpLatencyMs": {"p50": quantile(http_ms, 50), "p95": quantile(http_ms, 95),
                          "p99": quantile(http_ms, 99)},
        "orderLatencyMs": {"p50": quantile(order_ms, 50), "p95": quantile(order_ms, 95),
                           "p99": quantile(order_ms, 99)},
        "mysqlClockOffsetMs": round(db_clock_offset, 3),
        "databaseRowLockWaitsBefore": db_before,
        "databaseRowLockWaitsAfter": db_after,
        "reconciliation": reconciliation["status"],
        "createdAtWindowMs": [min(x[0] for x in by_request.values()),
                              max(x[0] for x in by_request.values())],
        "startWallMs": start_wall,
    })
    print(json.dumps(records[-1], ensure_ascii=False), flush=True)

monitor_stop.set()
monitor_thread.join(timeout=20)
report = {
    "date": "2026-10-14", "workers": WORKERS, "usersPerRound": USERS,
    "rounds": records,
    "medianOrderP95Ms": statistics.median(r["orderLatencyMs"]["p95"] for r in records),
    "allCLEAN": all(r["reconciliation"] == "CLEAN" for r in records),
    "verifiedContainerWorkers": int(configured_workers),
    "resourceSamples": resource_samples,
    "method": "owned S7 WSL stack; real HTTP/Redis/RocketMQ/Java/MySQL; 64 unique users; stock 64 per SKU; only C++ HTTP worker count changes. HTTP uses monotonic client clock; DB persistence timestamps are corrected by a before-round MySQL-vs-client wall-clock offset.",
}
out = ROOT / "tests" / "reports" / "wsl" / f"s14-workers-{WORKERS}.json"
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
assert report["allCLEAN"]
print(f"REPORT {out.relative_to(ROOT)} medianOrderP95Ms={report['medianOrderP95Ms']}", flush=True)
