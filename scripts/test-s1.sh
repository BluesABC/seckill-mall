#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
source scripts/env-wsl.sh
mkdir -p build/wsl tests/reports/wsl
exec > >(tee tests/reports/wsl/s1-run.log) 2>&1
trap 'result=$?; echo "ExitCode=$result"' EXIT
[[ "$(uname -s)" == Linux ]] || { echo 'Run inside WSL/Linux'; exit 2; }
echo "WSL S1 started $(date -u +%FT%TZ)"
python3 --version
docker version --format '{{.Server.Version}}'
py="$project_root/build/wsl/venv/bin/python"
if [[ ! -x "$py" ]] || ! "$py" -m pip --version >/dev/null 2>&1; then
  python3 -m venv --copies build/wsl/venv
fi
"$py" -m pip install -r scripts/requirements-validation.txt -r scripts/requirements-integration.txt
docker compose -p seckill-mall-s1 --env-file deploy/.env.s1.example -f deploy/compose.infra.yml up -d --wait --wait-timeout 180
export MALL_DB_PORT=13306 MALL_DB_USER=root MALL_DB_PASSWORD=s1-local-root-only
export MALL_REDIS_URL=redis://127.0.0.1:16379/0
"$py" scripts/data.py migrate
"$py" scripts/data.py seed
"$py" scripts/data.py preheat
"$py" tests/test_s1.py
"$py" tests/test_s1_recovery.py
"$py" scripts/verify_contracts.py
echo 'PASS S1: real MySQL/Redis integration; no RocketMQ/order-service/full mall acceptance.'
# Leave dedicated development containers running; never delete volumes automatically.
