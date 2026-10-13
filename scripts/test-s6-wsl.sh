#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
[[ "$(uname -s)" == Linux ]] || { echo 'Run in WSL/Linux'; exit 2; }
export MALL_STACK_PROJECT=seckill-mall-s6
export MALL_STACK_ENV="${MALL_STACK_ENV:-$root/deploy/.env.stack}"
mkdir -p tests/reports/wsl
exec > >(tee tests/reports/wsl/s6-deploy.log) 2>&1
date -u
uname -a
cat /etc/os-release
docker version --format '{{.Client.Version}} / {{.Server.Version}}'
docker compose version
python3 --version
python3 scripts/prepare-deploy.py --path "$MALL_STACK_ENV"
dc=(docker compose -p "$MALL_STACK_PROJECT" --env-file "$MALL_STACK_ENV" -f deploy/compose.yml)
# Refuse existing volumes: this acceptance requires fresh, owned data.
if [[ -n "$(docker volume ls -q --filter label=com.docker.compose.project=seckill-mall-s6)" ]]; then
  echo 'S6 test volumes already exist. Preserve/inspect them; use a new clean test environment before rerunning.'
  exit 2
fi
"${dc[@]}" config --quiet
"${dc[@]}" build
"${dc[@]}" up -d --wait --wait-timeout 300
cd "$root"
"${dc[@]}" run --rm seed
# Docker Desktop can replace a DrvFs mount while building/binding sources.
# Refresh the cwd handle before invoking native tools and use an absolute file.
cd "$root"
python3 "$root/tests/test_s6.py"
cd "$root"
source scripts/env-wsl.sh
node --version
mkdir -p build/wsl/browser
cp tests/browser/package.json tests/browser/package-lock.json build/wsl/browser/
(cd build/wsl/browser && npm ci --no-audit --no-fund && npx playwright install chromium)
node tests/browser/s6-deployment.cjs
"${dc[@]}" ps -a
echo 'EXIT 0: S6 native Linux Docker acceptance complete'
