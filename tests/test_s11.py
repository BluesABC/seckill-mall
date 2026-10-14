"""Measure RocketMQ consumer recovery after the order process is force-killed."""
import argparse
import json
import subprocess
import time
from pathlib import Path

from stack_client import *

REPORT = ROOT / "tests/reports/wsl" / os.environ.get("S11_REPORT", "s11-recovery.json")


def one_trial(label, maximum_seconds):
    admin = login()
    user = fixture_users(1)[0]
    activity_id, sku_id = activity(admin, 1, f"s11-{label}-{uuid.uuid4().hex[:8]}")
    request = prepare(user, activity_id, sku_id)

    dc("stop", "-t", "1", "order")
    code, response = buy(request)
    assert code == 202, (code, response)

    started = time.monotonic()
    start_service("order")
    wait(lambda: call("GET", "/health/order")[0] == 200, 90)
    last_query = {}
    def query_order():
        code, value = call(
            "GET",
            f"/api/order/status?activityId={request['activity']}&skuId={request['sku']}&requestId={request['requestId']}",
            token=request["token"],
        )
        last_query.update({"httpStatus": code, "body": value})
        return value if code == 200 and value.get("orderId") else None
    try:
        persisted = wait(query_order, maximum_seconds + 5)
    except AssertionError:
        row = sql(
            "SELECT r.status,o.id,o.status FROM seckill_requests r LEFT JOIN orders o "
            f"ON o.reservation_id=r.reservation_id WHERE r.request_id='{request['requestId']}'"
        )
        print("S11 recovery timeout diagnostics", json.dumps({"lastQuery": last_query, "dbRow": row}), flush=True)
        raise
    elapsed = round(time.monotonic() - started, 3)
    assert persisted["orderState"] == "PENDING_PAYMENT", persisted
    assert elapsed <= maximum_seconds, f"consumer recovery took {elapsed:.3f}s"
    reconciliation = clean()
    assert reconciliation["status"] == "CLEAN", reconciliation

    result = {
        "label": label,
        "orderAcceptedWhileOrderServiceStopped": True,
        "orderVisibleSeconds": elapsed,
        "state": persisted["orderState"],
        "reconciliation": reconciliation["status"],
    }
    print("PASS S11 hard-stop recovery", json.dumps(result), flush=True)
    return result


parser = argparse.ArgumentParser()
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument("--baseline", action="store_true")
group.add_argument("--verify", action="store_true")
parser.add_argument("--rounds", type=int, default=3)
parser.add_argument("--maximum-seconds", type=float, default=120)
args = parser.parse_args()

if args.baseline:
    raw_proxy_config = dc(
        "exec", "-T", "broker", "sh", "-c",
        'if [ -f /home/rocketmq/rocketmq-5.3.2/conf/rmq-proxy.json ]; then cat /home/rocketmq/rocketmq-5.3.2/conf/rmq-proxy.json; else printf "{}"; fi',
    )
    baseline_config = json.loads(raw_proxy_config)
    assert not ({"channelExpiredTimeout", "defaultInvisibleTimeMills"} & baseline_config.keys()), (
        "Baseline requires default consumer membership/invisible expiry"
    )
    result = {
        "phase": "unmodified-rocketmq-proxy",
        "proxyConfig": baseline_config,
        "results": [one_trial("baseline", 120)],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
else:
    raw_proxy_config = dc(
        "exec", "-T", "broker", "sh", "-c",
        'if [ -f /home/rocketmq/rocketmq-5.3.2/conf/rmq-proxy.json ]; then cat /home/rocketmq/rocketmq-5.3.2/conf/rmq-proxy.json; else printf "{}"; fi',
    )
    proxy_config = json.loads(raw_proxy_config)
    expected_field = os.environ.get("S11_EXPECT_PROXY_FIELD")
    expected_value = os.environ.get("S11_EXPECT_PROXY_VALUE")
    if expected_field is not None and expected_value is not None:
        assert proxy_config.get(expected_field) == int(expected_value), proxy_config
    assert args.rounds == 3, "Acceptance requires exactly three independent crash rounds"
    result = json.loads(REPORT.read_text(encoding="utf-8"))
    assert result["phase"] == "unmodified-rocketmq-proxy", result
    result["verificationProxyConfig"] = proxy_config
    result["verificationResults"] = []
    for attempt in range(1, args.rounds + 1):
        result["verificationResults"].append(
            one_trial(f"verify-{attempt}", args.maximum_seconds)
        )
        REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    assert all(r["reconciliation"] == "CLEAN" for r in result["verificationResults"])
    print("PASS S11 forced-recovery 3/3", flush=True)
