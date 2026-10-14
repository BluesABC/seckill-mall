#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
[[ "$(uname -s)" == Linux ]] || { echo 'Run inside WSL/Linux'; exit 2; }
[[ -f deploy/.env.s7 ]] || { echo 'S7 private environment is missing; run the S7 setup first'; exit 2; }
export MALL_STACK_PROJECT=seckill-mall-s7
export MALL_STACK_ENV="$project_root/deploy/.env.s7"
compose=(docker compose -p "$MALL_STACK_PROJECT" --env-file "$MALL_STACK_ENV" -f deploy/compose.yml -f deploy/compose.s7.yml)
[[ -n "$("${compose[@]}" ps -q order)" ]] || { echo 'Owned S7 order service is missing'; exit 2; }
mkdir -p tests/reports/wsl
exec > >(tee tests/reports/wsl/s8-test-run.log) 2>&1
trap 'result=$?; echo "ExitCode=$result"' EXIT
python3 tests/test_s8.py
