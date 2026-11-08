#!/bin/sh
set -eu
# Sentinel 会重写配置记录选主结果。每个实例使用自己的持久卷。
if [ ! -f /data/sentinel.conf ]; then
  cat >/data/sentinel.conf <<CONFIG
port 26379
dir /data
sentinel monitor mall-redis ${MALL_REDIS_NETWORK_PREFIX}.201 6379 2
sentinel down-after-milliseconds mall-redis 3000
sentinel failover-timeout mall-redis 15000
sentinel parallel-syncs mall-redis 1
CONFIG
fi
exec docker-entrypoint.sh redis-sentinel /data/sentinel.conf
