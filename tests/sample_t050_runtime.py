"""Read-only, activity-scoped runtime sample for an owned S7 capacity run."""
import argparse
import json
import math
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
from stack_client import ROOT, PROJECT, redis, sql

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--activity-id', type=int, required=True)
parser.add_argument('--sku-id', type=int, required=True)
args = parser.parse_args()
assert args.activity_id > 0 and args.sku_id > 0
rows = sql('SELECT status,COUNT(*) FROM orders WHERE activity_id='
           f'{args.activity_id} GROUP BY status').splitlines()
orders = {state: int(count) for state, count in (row.split('\t') for row in rows)}
pending, age = sql('SELECT COUNT(*),GREATEST(COALESCE(MAX(CAST(UNIX_TIMESTAMP(NOW(3))*1000 AS SIGNED)-CAST(o.created_at_ms AS SIGNED)),0),0) '
                  'FROM outbox_events o JOIN seckill_requests r ON r.reservation_id=o.reservation_id '
                  f'WHERE r.activity_id={args.activity_id} AND o.status=\'PENDING\'').split('\t')
lines = subprocess.check_output(['docker', 'logs', '--since', '60s', f'{PROJECT}-seckill-1'],
                                text=True, stderr=subprocess.STDOUT).splitlines()
handlers = []
for line in lines:
    try:
        row = json.loads(line)
        if row.get('path') == '/api/seckill/buy':
            handlers.append(row)
    except (ValueError, TypeError):
        pass
latencies = sorted(row['rtUs']/1000 for row in handlers)
result = {'at': datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds'),
          'activityId': args.activity_id, 'ordersByStatus': orders,
          'outboxPending': int(pending), 'oldestPendingOutboxAgeMs': int(age),
          'relayPending': int(redis('HGET', f'seckill:{{{args.activity_id}:{args.sku_id}}}:ledger', 'pendingCount') or 0),
          'cppHandlerCountLast60s': len(handlers),
          'cppHandlerErrorsLast60s': sum(row['status'] >= 500 for row in handlers),
          'cppHandlerP95MsLast60s': latencies[math.ceil(len(latencies)*.95)-1] if latencies else None,
          'measurement': 'Handler latency excludes ingress queue/network; final gate uses client latency. Read-only snapshot.'}
path = ROOT / 'tests/reports/wsl/t050-runtime-samples.json'
samples = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
samples.append(result)
path.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False))
