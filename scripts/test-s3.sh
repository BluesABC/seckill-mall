#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
mkdir -p build/wsl tests/reports/wsl
exec > >(tee tests/reports/wsl/s3-run.log) 2>&1
trap 'result=$?; echo "ExitCode=$result"' EXIT
[[ "$(uname -s)" == Linux ]] || { echo 'Run in WSL/Linux'; exit 2; }
source scripts/env-wsl.sh
python3 --version
java -version
docker version --format '{{.Server.Version}}'
docker compose -p seckill-mall-s1 --env-file deploy/.env.s1.example -f deploy/compose.infra.yml up -d --wait redis
bash scripts/ensure-rocketmq-topic.sh
bash scripts/configure-order-consumer-group.sh
bash scripts/setup-rocketmq-sdk-wsl.sh
sdk_prefix="$project_root/build/wsl/rocketmq-sdk-install"
cmake -S . -B build/wsl/cpp-s3 -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON \
  -DMALL_WITH_ROCKETMQ=ON -DCMAKE_PREFIX_PATH="$sdk_prefix"
cmake --build build/wsl/cpp-s3 -j2
ctest --test-dir build/wsl/cpp-s3 --output-on-failure
mvn -B -f src/order/pom.xml -Dmall.build.directory="$project_root/build/wsl/order-target" verify
mvn -B -f src/order/pom.xml dependency:build-classpath \
  -Dmdep.outputFile="$project_root/build/wsl/rocketmq-java.classpath"
py="$project_root/build/wsl/venv/bin/python"
[[ -x "$py" ]] || { echo 'WSL Python environment missing; see docs/TESTING.md'; exit 2; }
"$py" -m pip install -r scripts/requirements-validation.txt -r scripts/requirements-integration.txt
"$py" tests/test_s3.py
"$py" scripts/verify_contracts.py
echo 'PASS S3 transport: real RocketMQ C++/Java SDK, single-broker fault cases.'
