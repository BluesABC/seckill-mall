#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
source scripts/env-wsl.sh
mkdir -p build/wsl tests/reports/wsl
exec > >(tee tests/reports/wsl/s2-run.log) 2>&1
trap 'result=$?; echo "ExitCode=$result"' EXIT
[[ "$(uname -s)" == Linux ]] || { echo 'Run inside WSL/Linux'; exit 2; }
docker compose -p seckill-mall-s1 --env-file deploy/.env.s1.example -f deploy/compose.infra.yml up -d --wait redis
cmake -S . -B build/wsl/cpp -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
cmake --build build/wsl/cpp -j2
ctest --test-dir build/wsl/cpp --output-on-failure
py="$project_root/build/wsl/venv/bin/python"
[[ -x "$py" ]] || { echo 'Prepare WSL venv using TESTING.md first'; exit 2; }
"$py" -m pip install -r scripts/requirements-validation.txt -r scripts/requirements-integration.txt
"$py" tests/test_s2.py
"$py" scripts/verify_contracts.py
echo 'PASS S2 HTTP/Redis stage; actual RocketMQ adapter is S3.'
