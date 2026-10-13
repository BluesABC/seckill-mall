#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
source scripts/env-wsl.sh
mkdir -p build/wsl tests/reports/wsl
exec > >(tee tests/reports/wsl/s4-run.log) 2>&1
trap 'result=$?; echo "ExitCode=$result"' EXIT
[[ "$(uname -s)" == Linux ]] || { echo 'Run in WSL/Linux'; exit 2; }
uname -r
java -version
docker version --format '{{.Server.Version}}'
docker compose -p seckill-mall-s1 --env-file deploy/.env.s1.example -f deploy/compose.infra.yml up -d --wait --wait-timeout 180
bash scripts/ensure-rocketmq-topic.sh
bash scripts/configure-order-consumer-group.sh
bash scripts/setup-rocketmq-sdk-wsl.sh
cmake -S . -B build/wsl/cpp-s3 -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON -DMALL_WITH_ROCKETMQ=ON -DCMAKE_PREFIX_PATH="$project_root/build/wsl/rocketmq-sdk-install"
cmake --build build/wsl/cpp-s3 -j2
ctest --test-dir build/wsl/cpp-s3 --output-on-failure
mvn -B -f src/order/pom.xml -Dmall.build.directory="$project_root/build/wsl/order-target" verify
py="$project_root/build/wsl/venv/bin/python"
[[ -x "$py" ]] || { echo 'WSL Python environment missing'; exit 2; }
"$py" -m pip install -r scripts/requirements-validation.txt -r scripts/requirements-integration.txt
export MALL_DB_USER=root MALL_DB_PASSWORD=s1-local-root-only MALL_DB_PORT=13306
export MALL_REDIS_URL=redis://127.0.0.1:16379/0
"$py" tests/test_s4.py
"$py" scripts/verify_contracts.py
echo 'PASS S4 real HTTP/C++/RocketMQ/Java/MySQL/Redis business integration.'
