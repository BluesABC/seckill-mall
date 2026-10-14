#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "$(uname -s)" == Linux ]] || exit 2
cd "$root"
project=seckill-mall-s7
env_file="$root/deploy/.env.s7"
dc=(docker compose -p "$project" --env-file "$env_file" -f "$root/deploy/compose.yml" -f "$root/deploy/compose.s7.yml")
[[ -f "$env_file" ]] || { echo 'Missing owned S7 env file; start the S7 acceptance stack first'; exit 2; }
[[ -n "$(docker volume ls -q --filter label=com.docker.compose.project="$project")" ]] || { echo 'Owned S7 volumes not found; start the S7 acceptance stack first'; exit 2; }
restore_default() {
  unset MALL_HTTP_WORKERS
  "${dc[@]}" up -d --no-deps --force-recreate seckill >/dev/null || true
}
trap restore_default EXIT
python3 -m py_compile tests/test_s14_workers.py
for workers in 8 16 24 32 48 64; do
  export MALL_HTTP_WORKERS="$workers"
  "${dc[@]}" up -d --no-deps --force-recreate seckill
  python3 - "$workers" <<'PY'
import subprocess, sys
sys.path.insert(0, "tests")
from stack_client import call, wait
n = sys.argv[1]
wait(lambda: call("GET", "/health/seckill")[0] == 200, 120)
env = subprocess.check_output(
    ["docker", "inspect", "--format", "{{range .Config.Env}}{{println .}}{{end}}",
     "seckill-mall-s7-seckill-1"], text=True)
assert f"MALL_HTTP_WORKERS={n}" in env, "container did not apply selected worker count"
print(f"verified container worker count: {n}")
PY
  python3 tests/test_s14_workers.py "$workers"
done
echo 'S14 worker sweep complete; restoring the default worker count.'
