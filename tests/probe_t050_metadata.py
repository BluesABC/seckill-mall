"""Read-only metadata probe on an existing owned-S7 activity ledger."""
import argparse
import json
import statistics
import time
from pathlib import Path
from stack_client import ROOT, call, redis

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--activity-id', type=int, required=True)
parser.add_argument('--sku-id', type=int, required=True)
parser.add_argument('--report-name', choices=['t050-metadata-before.json', 't050-metadata-after.json'], required=True)
args = parser.parse_args()

def output_bytes():
    return int(dict(line.split(':', 1) for line in redis('INFO', 'stats').splitlines()
                    if ':' in line)['total_net_output_bytes'])

before = output_bytes()
samples = []
for _ in range(20):
    started = time.monotonic()
    status, body = call('GET', f'/api/seckill/info?activityId={args.activity_id}&skuId={args.sku_id}')
    assert status == 200, (status, body)
    samples.append(round((time.monotonic() - started) * 1000, 3))
result = {'samplesMs': samples, 'medianMs': statistics.median(samples),
          'redisOutputBytesDelta': output_bytes() - before,
          'ledgerFields': int(redis('HLEN', f'seckill:{{{args.activity_id}:{args.sku_id}}}:ledger')),
          'scope': 'Read-only diagnostic; global Redis byte counter includes background traffic.'}
(ROOT / 'tests/reports/wsl' / args.report_name).write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result))
