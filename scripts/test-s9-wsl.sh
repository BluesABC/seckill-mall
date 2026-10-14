#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
source scripts/env-wsl.sh
[[ "$(uname -s)" == Linux ]] || { echo 'Run inside WSL/Linux'; exit 2; }
[[ -f deploy/.env.s7 ]] || { echo 'S7 isolated test stack is missing'; exit 2; }
[[ -n "$(docker compose -p seckill-mall-s7 --env-file deploy/.env.s7 -f deploy/compose.yml -f deploy/compose.s7.yml ps -q order)" ]] || { echo 'S7 order service is missing'; exit 2; }
export MALL_WEB_PORT="${MALL_WEB_PORT:-15173}"
mkdir -p tests/reports/wsl
exec > >(tee tests/reports/wsl/s9-run.log) 2>&1
trap 'result=$?; echo "ExitCode=$result"' EXIT
date -u
cat /etc/os-release
docker compose -p seckill-mall-s1 --env-file deploy/.env.s1.example -f deploy/compose.infra.yml up -d --wait --wait-timeout 180
bash scripts/ensure-rocketmq-topic.sh
bash scripts/test-s5-wsl.sh
docker compose -p seckill-mall-s7 --env-file deploy/.env.s7 -f deploy/compose.yml -f deploy/compose.s7.yml up -d --build --no-deps --force-recreate --wait --wait-timeout 180 order
MALL_STACK_PROJECT=seckill-mall-s7 MALL_STACK_ENV="$root/deploy/.env.s7" build/wsl/venv/bin/python tests/test_s9_catalog.py
build/wsl/venv/bin/python scripts/verify_contracts.py
echo 'PASS S9 server catalog pagination; browser, API and WSL contract checks complete.'
