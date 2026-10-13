#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
policy='{"type":"CUSTOMIZED","customizedRetryPolicy":{"next":[1000,2000,4000,8000,16000,30000,30000,30000]}}'
docker compose -p seckill-mall-mq -f deploy/compose.mq.yml up -d --wait --wait-timeout 180
docker exec seckill-mall-mq-broker-1 sh mqadmin updateSubGroup \
  -n namesrv:9876 -b 127.0.0.1:10911 -g mall_order_v1 -r 8 -p "$policy"
