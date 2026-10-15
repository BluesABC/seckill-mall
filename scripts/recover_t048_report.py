"""Rebuild a T048 report from its client checkpoint and live durable evidence."""
import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from analyze_order_stages import parse, summarize  # noqa: E402
from stack_client import PROJECT, sql, reconcile  # noqa: E402


def quantile(values, pct):
    values = sorted(values)
    return (round(values[min(len(values) - 1, math.ceil(len(values) * pct / 100) - 1)], 3)
            if values else None)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="tests/reports/wsl/t048-sustained-client-checkpoint.json")
    parser.add_argument("--report-name", default="t048-sustained-recovered.json")
    args = parser.parse_args()
    if not re.fullmatch(r"t048-[a-z0-9-]+\.json", args.report_name):
        parser.error("report name must be a simple t048-*.json filename")
    checkpoint = json.loads((ROOT / args.checkpoint).read_text(encoding="utf-8"))
    activity_id = int(checkpoint["activityId"])
    reservation_rows = sql(
        f"SELECT request_id,reservation_id,status FROM seckill_requests WHERE activity_id={activity_id}"
    ).splitlines()
    request_rows = {}
    reservation_ids = set()
    for line in reservation_rows:
        request_id, reservation_id, status = line.split("\t")
        request_rows[request_id] = {"reservationId": reservation_id, "state": status}
        reservation_ids.add(reservation_id)
    order_rows = sql(
        "SELECT r.request_id,o.status,o.created_at_ms FROM orders o "
        "JOIN seckill_requests r ON r.reservation_id=o.reservation_id "
        f"WHERE r.activity_id={activity_id}"
    ).splitlines()
    orders = {}
    for line in order_rows:
        request_id, status, created_at_ms = line.split("\t")
        orders[request_id] = {"status": status, "createdAtMs": int(created_at_ms)}

    logs = []
    for service in ("relay", "order"):
        logs.extend(subprocess.check_output(
            ["docker", "logs", "--since", "2h", f"{PROJECT}-{service}-1"],
            text=True, stderr=subprocess.STDOUT).splitlines())
    reservation_pattern = re.compile(r"\breservationId=([a-f0-9-]{36})\b")
    relevant = []
    for line in logs:
        match = reservation_pattern.search(line)
        if "event=seckill_stage" in line and match and match.group(1) in reservation_ids:
            relevant.append(line)
    events, malformed, duplicates = parse(relevant)
    stages = summarize(events, malformed, duplicates)

    responses = checkpoint.get("requestResults", [])
    statuses = checkpoint.get("httpStatusCounts", {})
    business_codes = checkpoint.get("businessCodeCounts", {})
    accepted_ids = {row["requestId"] for row in responses if row.get("status") == 202}
    http_accepted_persisted = accepted_ids.issubset(orders)
    order_statuses = {}
    for row in orders.values():
        order_statuses[row["status"]] = order_statuses.get(row["status"], 0) + 1
    outbox_rows = sql(
        "SELECT status,COUNT(*) FROM outbox_events WHERE reservation_id IN "
        f"(SELECT reservation_id FROM seckill_requests WHERE activity_id={activity_id}) GROUP BY status"
    ).splitlines()
    outbox = {status: int(count) for status, count in (row.split("\t") for row in outbox_rows)}
    pending_count = int(sql(f"SELECT COUNT(*) FROM seckill_requests WHERE activity_id={activity_id} "
                            "AND status IN ('RESERVED','QUEUED')"))
    reconciliation = reconcile(activity_id=activity_id, limit=100000)

    accepted_latencies = [row["latencyMs"] for row in responses if row.get("status") == 202]
    durable_latencies = [row["firstSeenAfterRequestMs"]
                         for row in checkpoint.get("databaseVisibleOrders", {}).values()]
    server_5xx = sum(count for status, count in statuses.items()
                     if status.isdigit() and int(status) >= 500)
    total = int(checkpoint["submitted"])
    server_5xx_pct = server_5xx * 100 / total if total else 0
    accepted_count = int(checkpoint.get("accepted", 0))
    stage_complete = (
        stages["reservations"] == len(request_rows)
        and stages["stageCounts"].get("relay_publish", 0) == len(request_rows)
        and stages["stageCounts"].get("consumer_received", 0) == len(request_rows)
        and stages["malformedStageLines"] == 0
    )
    observed_seconds = checkpoint.get("observedSubmissionSeconds")
    observed_qps = total / observed_seconds if observed_seconds else None
    durable_p95 = quantile(durable_latencies, 95)
    durable_p99 = quantile(durable_latencies, 99)
    gate = {
        "offeredRateAtLeastTarget": observed_qps is not None
            and observed_qps >= float(checkpoint["offeredQps"]) * .99,
        "eligibleRequestsAcceptedAtLeast99_5Percent": accepted_count / total >= .995 if total else False,
        "server5xxAtMost0_1Percent": server_5xx_pct <= .1,
        "acceptedBuyApiP95AtMost500ms": quantile(accepted_latencies, 95) is not None
            and quantile(accepted_latencies, 95) <= 500,
        "durableOrderP95AtMost3000ms": durable_p95 is not None and durable_p95 <= 3000,
        "durableOrderP99AtMost8000ms": durable_p99 is not None and durable_p99 <= 8000,
        "allHttpAcceptedOrdersPersisted": http_accepted_persisted,
        "stageTelemetryComplete": stage_complete,
        "outboxDrained": outbox.get("PENDING", 0) == 0,
        "inventoryReconciliationClean": reconciliation.get("status") == "CLEAN",
    }
    report = {
        "date": checkpoint.get("date"),
        "platform": "WSL2 Ubuntu; Docker Desktop Linux engine",
        "activityName": checkpoint.get("activityName"),
        "activityId": str(activity_id),
        "skuId": checkpoint.get("skuId"),
        "cppHttpWorkers": checkpoint.get("cppHttpWorkers"),
        "mqConsumerThreads": checkpoint.get("mqConsumerThreads"),
        "mqQueueCount": checkpoint.get("mqQueueCount"),
        "offeredQps": checkpoint.get("offeredQps"),
        "durationSeconds": checkpoint.get("durationSeconds"),
        "submitted": total,
        "observedSubmissionSeconds": observed_seconds,
        "observedSubmissionQps": round(observed_qps, 3) if observed_qps else None,
        "accepted": accepted_count,
        "httpStatusCounts": statuses,
        "businessCodeCounts": business_codes,
        "server5xxCount": server_5xx,
        "server5xxRatePercent": round(server_5xx_pct, 4),
        "buyApiLatencyMsAcceptedOnly": checkpoint.get("buyApiLatencyMsAcceptedOnly"),
        "requestToDurableOrderMs": {f"p{p}": quantile(durable_latencies, p)
                                    for p in (50, 95, 99)},
        "requestToDurableObservedCount": len(durable_latencies),
        "persistedReservations": len(request_rows),
        "persistedOrders": len(orders),
        "ordersByStatus": order_statuses,
        "allHttpAcceptedOrdersPersisted": http_accepted_persisted,
        "pendingReservationRequests": pending_count,
        "stageTelemetry": stages,
        "stageTelemetryComplete": stage_complete,
        "outboxStatus": outbox,
        "reconciliation": reconciliation,
        "reportSource": "client response checkpoint plus recovered database/container log evidence",
        "temporaryGateResults": gate,
        "temporaryGateResultsPassed": all(value is True for value in gate.values()),
        "sameHostWslLimit": "Not an independent production capacity proof.",
    }
    out = ROOT / "tests" / "reports" / "wsl" / args.report_name
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out)
    print(json.dumps({"report": str(out.relative_to(ROOT)), "activityId": activity_id,
                      "accepted": accepted_count, "orders": len(orders),
                      "outboxPending": outbox.get("PENDING", 0),
                      "reconciliation": reconciliation.get("status"),
                      "capacityPassed": report["temporaryGateResultsPassed"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
