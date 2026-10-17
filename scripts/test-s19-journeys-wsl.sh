#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
[[ "$(uname -s)" == Linux ]] || { echo 'Run in WSL/Linux'; exit 2; }
if [[ "${1:-}" == --check ]]; then
  [[ $# == 2 ]] || exit 2
  exec python3 scripts/check_journey_gate.py "$2"
fi
run_args=("$@")
report=s19-mixed-journeys.json
smoke=0
while (( $# )); do
  case "$1" in
    --smoke) smoke=1; shift ;;
    --report) [[ $# -ge 2 ]] || exit 2; report="$2"; shift 2 ;;
    *) echo 'Usage: --report s19-NAME.json [--smoke], or --check REPORT'; exit 2 ;;
  esac
done
[[ "$report" =~ ^s19-[a-z0-9-]+\.json$ ]] || exit 2
[[ ! -e "tests/reports/wsl/$report" ]] || { echo 'Refuse overwriting evidence'; exit 2; }
mkdir -p build/wsl
exec 9>build/wsl/capacity.lock
flock -n 9 || { echo 'Another capacity test is running'; exit 2; }
dc=(docker compose -p seckill-mall-s7 --env-file deploy/.env.s7 -f deploy/compose.yml -f deploy/compose.s7.yml)
read -r previous_workers previous_queue < <(python3 - <<'PY'
import json,subprocess,sys
from pathlib import Path
sys.path.insert(0,'tests')
from stack_client import PROJECT,ENV,PORT
assert PROJECT=='seckill-mall-s7' and ENV.resolve()==Path('deploy/.env.s7').resolve(), 'Owned S7 environment required'
gateway=json.loads(subprocess.check_output(['docker','inspect','seckill-mall-s7-gateway-1']))[0]
assert int(gateway['NetworkSettings']['Ports']['80/tcp'][0]['HostPort'])==PORT, 'HTTP target must be the owned S7 gateway'
x=json.loads(subprocess.check_output(['docker','inspect','seckill-mall-s7-seckill-1']))[0]
assert x['Config']['Labels']['com.docker.compose.project']=='seckill-mall-s7'
e=dict(s.split('=',1) for s in x['Config']['Env'] if '=' in s)
print(int(e['MALL_HTTP_WORKERS']),int(e['MALL_HTTP_QUEUE']))
PY
)
restore() {
  result=$?
  trap - EXIT
  MALL_HTTP_WORKERS="$previous_workers" MALL_HTTP_QUEUE="$previous_queue" \
    "${dc[@]}" up -d --no-deps --force-recreate --wait seckill > build/wsl/s19-restore.log 2>&1 || result=1
  exit "$result"
}
trap restore EXIT
MALL_HTTP_WORKERS=32 MALL_HTTP_QUEUE=128 "${dc[@]}" up -d --no-deps --force-recreate --wait seckill > build/wsl/s19-configure.log 2>&1
python3 - <<'PY'
import sys
sys.path.insert(0,'tests')
from stack_client import call,wait
wait(lambda:all(call('GET',p)[0]==200 for p in ('/health/seckill','/health/order')))
PY
python3 tests/load_s19_journeys.py "${run_args[@]}"
if (( smoke == 0 )); then
  python3 scripts/check_journey_gate.py "tests/reports/wsl/$report" \
    --output "tests/reports/wsl/${report%.json}-gate.json"
fi
