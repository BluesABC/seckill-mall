#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
source scripts/env-wsl.sh
[[ "$(uname -s)" == Linux && "$(command -v python3)" != *.exe ]] || { echo 'Run inside WSL/Linux'; exit 2; }
[[ -f deploy/.env.s7 ]] || { echo 'Owned S7 acceptance environment is missing'; exit 2; }
export MALL_STACK_PROJECT=seckill-mall-s7 MALL_STACK_ENV="$root/deploy/.env.s7"
export S11_REPORT="${S11_REPORT:-s11-recovery.json}"
compose=(docker compose -p "$MALL_STACK_PROJECT" --env-file "$MALL_STACK_ENV" -f deploy/compose.yml -f deploy/compose.s7.yml)
[[ -n "$("${compose[@]}" ps -q order)" && -n "$("${compose[@]}" ps -q broker)" ]] || { echo 'Owned S7 order/broker services must be running'; exit 2; }
mkdir -p tests/reports/wsl
exec > >(tee -a tests/reports/wsl/s11-run.log) 2>&1
trap 'result=$?; echo "ExitCode=$result"' EXIT
date -u
cat /etc/os-release
uname -r
python3 --version
python3 tests/test_s11.py "$@"
