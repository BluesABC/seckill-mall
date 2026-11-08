#!/usr/bin/env bash
# 显式微信接入验证：官方SDK密码学测试 + 独立MySQL状态机，无真实商户/收款。
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
[[ "$(uname -s)" == Linux ]] || { echo 'WSL/Linux required'; exit 2; }
mkdir -p build/wsl tests/reports/wsl
mvn -B -f src/order/pom.xml -Dmall.build.directory="$root/build/wsl/order-target" verify
mvn -q -f src/order/pom.xml dependency:build-classpath -Dmdep.includeScope=test -Dmdep.outputFile="$root/build/wsl/t060-classpath.txt"
docker compose -p seckill-mall-s1 --env-file deploy/.env.s1.example -f deploy/compose.infra.yml up -d --wait --wait-timeout 180
export MALL_DB_USER=root MALL_DB_PASSWORD=s1-local-root-only MALL_DB_PORT=13306
build/wsl/venv/bin/python tests/wechat_database_probe.py
