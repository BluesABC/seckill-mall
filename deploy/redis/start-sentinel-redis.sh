#!/bin/sh
set -eu
# 冷启动时以两个 Sentinel 的一致视图恢复角色，避免静态副本参数覆盖上次选主。
prefix=${MALL_REDIS_NODE_IP%.*}
for attempt in $(seq 1 30); do
  votes=$(
    for sentinel in sentinel-1 sentinel-2 sentinel-3; do
      timeout 1 redis-cli -h "$sentinel" -p 26379 --raw SENTINEL get-master-addr-by-name mall-redis 2>/dev/null |
        awk -v prefix="$prefix" 'NR==1{ip=$0} NR==2 && $0=="6379" && (ip==prefix".201" || ip==prefix".202" || ip==prefix".203"){print ip}'
    done
  )
  primary=$(printf '%s\n' "$votes" | sort | uniq -c | awk '$1>=2 && $2!=""{print $2}')
  if [ -n "$primary" ]; then
    set -- redis-server --appendonly yes --appendfsync always --maxmemory-policy noeviction --replica-read-only yes
    if [ "$MALL_REDIS_NODE_IP" != "$primary" ]; then
      set -- "$@" --replicaof "$primary" 6379
    fi
    exec docker-entrypoint.sh "$@"
  fi
  sleep 1
done
echo 'No Redis Sentinel majority view at startup' >&2
exit 1
