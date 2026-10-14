"""Verify graceful order-consumer shutdown unregisters fast enough for recovery."""
import json, subprocess, time
from stack_client import *

admin = login()
results = []
for attempt in range(1, 4):
    user = fixture_users(1)[0]
    activity_id, sku_id = activity(admin, 1, f's8-graceful-restart-{attempt}')
    request = prepare(user, activity_id, sku_id)

    stop_started = time.monotonic()
    dc('stop', '-t', '30', 'order')
    stopped_at = time.monotonic()
    accepted, body = buy(request)
    assert accepted == 202, (accepted, body)

    start = time.monotonic()
    start_service('order')
    ready = wait(lambda: True if call('GET', '/health/order')[0] == 200 else None, 60)
    health_seconds = time.monotonic() - start
    persisted = wait(lambda: order(request), 60)
    order_seconds = time.monotonic() - start
    assert persisted['orderState'] == 'PENDING_PAYMENT'
    assert order_seconds <= 20, f'graceful consumer recovery took {order_seconds:.3f}s'

    logs = subprocess.check_output(
        ['docker', 'logs', PROJECT + '-order-1'], text=True, stderr=subprocess.STDOUT
    )
    assert 'order-consumer shutdown pending' not in logs
    reconciliation = clean()
    assert reconciliation['status'] == 'CLEAN'
    result = {
        'attempt': attempt,
        'stopSeconds': round(stopped_at - stop_started, 3),
        'orderAccepted': True,
        'orderServiceReadySeconds': round(health_seconds, 3),
        'orderVisibleSeconds': round(order_seconds, 3),
        'consumerCloseTimedOut': False,
        'reconciliation': reconciliation['status'],
    }
    results.append(result)
    print('PASS S8 graceful restart', json.dumps(result), flush=True)

report = {
    'date': '2026-10-14',
    'platform': 'WSL2 Ubuntu; isolated seckill-mall-s7 Compose project',
    'containerStopGraceSeconds': 30,
    'consumerCloseWaitSeconds': 20,
    'hardStopBaselineSeconds': 75.945,
    'acceptanceThresholdSeconds': 20,
    'results': results,
    'finalReconciliation': clean(),
}
assert report['finalReconciliation']['status'] == 'CLEAN'
target = ROOT / 'tests/reports/wsl/s8-graceful-recovery.json'
target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print('PASS S8 graceful consumer recovery 3/3', flush=True)
