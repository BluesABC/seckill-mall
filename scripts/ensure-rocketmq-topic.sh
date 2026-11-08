#!/usr/bin/env bash
# 职责：准备真实RocketMQ验收Topic及基础配置；是测试依赖准备，不是业务生产者。
# 运行口径与所需环境见 docs/TESTING.md；代码阅读导航见 docs/CODE-READING.md。
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
docker compose -p seckill-mall-mq -f deploy/compose.mq.yml up -d --wait --wait-timeout 180
docker exec seckill-mall-mq-broker-1 sh mqadmin updateTopic -n namesrv:9876 -b 127.0.0.1:10911 \
  -t seckill_reserved_v1 -r 4 -w 4 -a +message.type=NORMAL
