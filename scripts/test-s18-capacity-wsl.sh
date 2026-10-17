#!/usr/bin/env bash
# Run only against the already provisioned, owned S7 stack; never replace data.
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
[[ "$(uname -s)" == Linux ]] || { echo 'Run in WSL/Linux'; exit 2; }
if [[ "${1:-}" == --check ]]; then
  [[ $# == 2 ]] || { echo 'Usage: bash scripts/test-s18-capacity-wsl.sh --check REPORT'; exit 2; }
  exec python3 scripts/check_capacity_gate.py "$2"
fi
[[ $# == 0 ]] || { echo 'Usage: bash scripts/test-s18-capacity-wsl.sh [--check REPORT]'; exit 2; }
mkdir -p build/wsl tests/reports/wsl
exec 9>build/wsl/capacity.lock
flock -n 9 || { echo 'Another capacity acceptance is running'; exit 2; }
export SUSTAINED_QPS="${SUSTAINED_QPS:-15}"
export SUSTAINED_SECONDS="${SUSTAINED_SECONDS:-1800}"
export T048_REPORT_NAME="${T048_REPORT_NAME:-t048-s18-$(date +%Y%m%d-%H%M%S).json}"
[[ "$T048_REPORT_NAME" =~ ^t048-[a-z0-9-]+\.json$ ]] || exit 2
[[ ! -e "tests/reports/wsl/$T048_REPORT_NAME" ]] || { echo 'Refuse replacing an existing evidence report'; exit 2; }
python3 - <<'PY'
import json, os, subprocess, sys
sys.path.insert(0, 'tests')
from stack_client import PROJECT, ENV, call
assert PROJECT == 'seckill-mall-s7' and ENV.is_file(), 'Owned S7 stack required'
assert float(os.environ['SUSTAINED_QPS']) >= 15 and int(os.environ['SUSTAINED_SECONDS']) >= 1800, 'Full gate requires >=15 QPS and >=1800 seconds'
for endpoint in ('/health/live', '/health/seckill', '/health/order'):
    assert call('GET', endpoint)[0] == 200, f'Unhealthy endpoint: {endpoint}'
runtime = {}
for service in ('seckill', 'relay', 'order', 'broker', 'redis', 'mysql'):
    info = json.loads(subprocess.check_output(['docker','inspect',f'{PROJECT}-{service}-1'],text=True))[0]
    assert info['Config']['Labels']['com.docker.compose.project'] == PROJECT
    assert info['State']['Running'], f'{service} not running'
    env = dict(row.split('=',1) for row in info['Config'].get('Env',[]) if '=' in row)
    runtime[service] = {'imageId':info['Image']}
    for key in ('MALL_HTTP_WORKERS','MALL_HTTP_QUEUE','MALL_MQ_CONSUMER_THREADS','ORDER_PAYMENT_TTL_MS'):
        if key in env: runtime[service][key] = env[key]
    if service == 'order':
        assert int(env.get('ORDER_PAYMENT_TTL_MS','900000')) >= (int(os.environ['SUSTAINED_SECONDS']) + 600)*1000, 'Set the isolated test payment TTL to cover the timed run and cleanup; do not change live business TTL'
assert runtime['seckill']['imageId'] == runtime['relay']['imageId'], 'S7 seckill and relay must use the same current C++ build; recreate both after building'
print(json.dumps({'preflight':'PASS','project':PROJECT,'runtime':runtime}),flush=True)
PY
set +e
python3 tests/load_t048_sustained.py 2>&1 | tee build/wsl/s18-capacity-run.log
load_status=${PIPESTATUS[0]}
python3 scripts/check_capacity_gate.py "tests/reports/wsl/$T048_REPORT_NAME" --output "tests/reports/wsl/${T048_REPORT_NAME%.json}-gate.json"
gate_status=$?
set -e
[[ $load_status == 0 && $gate_status == 0 ]]
