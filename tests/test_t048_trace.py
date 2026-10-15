"""One live owned-S7 transaction proving stage-log correlation end to end."""
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
from stack_client import activity, buy, clean, fixture_users, login, order, prepare  # noqa: E402
from analyze_order_stages import parse, summarize  # noqa: E402

admin = login()
name = "T048-trace-" + uuid.uuid4().hex[:10]
activity_id, sku = activity(admin, 1, name)
user = fixture_users(1)[0]
plan = prepare(user, activity_id, sku)
accepted_status, accepted = buy(plan)
assert accepted_status == 202, accepted
persisted = None
deadline = time.monotonic() + 60
while time.monotonic() < deadline:
    persisted = order(plan)
    if persisted:
        break
    time.sleep(.2)
assert persisted, "accepted reservation did not become a durable order within 60 seconds"
assert persisted["orderState"] == "PENDING_PAYMENT", persisted
reconciliation = clean()

lines = []
for service in ("relay", "order"):
    lines.extend(subprocess.check_output(
        ["docker", "logs", "--since", "10m", f"{__import__('stack_client').PROJECT}-{service}-1"],
        text=True, stderr=subprocess.STDOUT).splitlines())
events, malformed, duplicates = parse(lines)
trace = events.get(persisted["reservationId"])
assert trace, f"missing correlated telemetry for reservation {persisted['reservationId']}"
assert "relay_publish" in trace and "consumer_received" in trace
assert ("order_transaction_committed" in trace
        or "order_transaction_failed" in trace)
summary = summarize({persisted["reservationId"]: trace}, malformed, duplicates)
assert summary["malformedStageLines"] == 0, summary
assert summary["stageCounts"]["committed"] == 1, summary
assert summary["latencyMs"]["mysqlTransactionMs"]["count"] == 1, summary
assert summary["latencyMs"]["relaySendToBrokerMs"]["count"] == 1, summary
report = {
    "date": "2026-10-15",
    "environment": "Ubuntu 24.04 / WSL2; owned seckill-mall-s7 Docker stack",
    "activityName": name,
    "reservationId": persisted["reservationId"],
    "orderId": persisted["orderId"],
    "durableStatus": persisted["orderState"],
    "reconciliation": {"status": reconciliation["status"],
                        "orders": reconciliation["orders"],
                        "alerts": reconciliation["alerts"]},
    "correlatedStages": trace,
    "analysis": summary,
    "scope": "instrumentation smoke test only; one transaction is not a capacity or SLA result",
}
out = ROOT / "tests" / "reports" / "wsl" / "t048-stage-trace.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"status": "PASS", "reservationId": persisted["reservationId"],
                  "stages": list(trace), "reconciliation": reconciliation["status"],
                  "report": str(out.relative_to(ROOT))}, ensure_ascii=False))
