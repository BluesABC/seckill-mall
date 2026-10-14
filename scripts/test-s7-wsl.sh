#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)";cd "$root"
[[ "$(uname -s)" == Linux ]] || exit 2
export MALL_STACK_PROJECT=seckill-mall-s7 MALL_STACK_ENV="$root/deploy/.env.s7"
mkdir -p build/wsl tests/reports/wsl/s7
exec > >(tee tests/reports/wsl/s7-run.log) 2>&1
date -u;cat /etc/os-release;uname -a
docker version --format '{{.Client.Version}} / {{.Server.Version}}'
docker info --format '{{.NCPU}} CPUs / {{.MemTotal}} bytes'
docker compose version;python3 --version;git rev-parse HEAD
[[ -z "$(docker volume ls -q --filter label=com.docker.compose.project=seckill-mall-s7)" ]] || { echo 'Owned S7 volumes exist; preserve evidence and choose a clean test environment'; exit 2; }
python3 scripts/prepare-deploy.py --path "$MALL_STACK_ENV"
python3 - <<'PY'
from pathlib import Path
p=Path('deploy/.env.s7');s=p.read_text().replace('18080','18081').replace('172.30.85','172.30.87').replace(r'172\.30\.85',r'172\.30\.87');p.write_text(s)
s=Path('deploy/nginx/nginx.conf').read_text().replace('rate=40r/s','rate=5000r/s').replace('burst=80','burst=5000');Path('build/wsl/s7-nginx.conf').write_text(s)
PY
dc=(docker compose -p "$MALL_STACK_PROJECT" --env-file "$MALL_STACK_ENV" -f "$root/deploy/compose.yml" -f "$root/deploy/compose.s7.yml")
"${dc[@]}" build
cd "$root";"${dc[@]}" up -d --wait --wait-timeout 300
cd "$root";"${dc[@]}" run --rm seed
cd "$root";python3 "$root/tests/test_s7.py"
python3 "$root/tests/load_s7.py"
"${dc[@]}" ps -a
echo 'EXIT 0: S7 faults/reconciliation/load acceptance complete'
