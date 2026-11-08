#!/usr/bin/env bash
# 职责：日常完整商城Compose入口。up会构建源码镜像、启动及首次种子；down保留命名数据卷。
# 运行口径与所需环境见 docs/TESTING.md；代码阅读导航见 docs/CODE-READING.md。
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
mode="${1:-up}"
env_file="${MALL_STACK_ENV:-$root/deploy/.env.stack}"
project="${MALL_STACK_PROJECT:-seckill-mall-stack}"
[[ "$project" =~ ^[a-z0-9][a-z0-9_-]+$ ]] || exit 2
[[ -f "$env_file" ]] || { echo 'Generate credentials: python3 scripts/prepare-deploy.py'; exit 2; }
env_args=(--env-file "$env_file")
compose_args=(-f deploy/compose.yml)
sentinel_mode=${MALL_STACK_SENTINEL:-0}
if [[ "$project" == seckill-mall-stack && ! -v MALL_STACK_SENTINEL ]]; then
  sentinel_mode=1
fi
if [[ "$sentinel_mode" == 1 ]]; then
  export MALL_REDIS_NETWORK_PREFIX="${MALL_REDIS_NETWORK_PREFIX:-172.30.85}"
  compose_args+=(-f deploy/compose.sentinel.yml)
fi
if [[ -n "${MALL_WECHAT_ENV:-}" ]]; then
  [[ -f "$MALL_WECHAT_ENV" ]] || { echo 'WeChat config file missing' >&2; exit 2; }
  env_args+=(--env-file "$MALL_WECHAT_ENV")
  compose_args+=(-f deploy/compose.wechat.yml)
fi
dc=(docker compose -p "$project" "${env_args[@]}" "${compose_args[@]}")
"${dc[@]}" config --quiet
# 必须有两个 Sentinel 报告同一主地址，才执行依赖主节点的运维操作。
sentinel_primary() {
  local node address
  for node in sentinel-1 sentinel-2 sentinel-3; do
    address=$("${dc[@]}" exec -T "$node" redis-cli -p 26379 --raw SENTINEL get-master-addr-by-name mall-redis 2>/dev/null | head -n 1) || continue
    case "$address" in
      "$MALL_REDIS_NETWORK_PREFIX".201|"$MALL_REDIS_NETWORK_PREFIX".202|"$MALL_REDIS_NETWORK_PREFIX".203) printf '%s\n' "$address";;
    esac
  done | sort | uniq -c | awk '$1>=2 {print $2}'
}
if [[ "$project" == seckill-mall-stack && "$sentinel_mode" != 1 && "$mode" == up ]]; then
  if [[ -n "$(docker ps -a --filter "label=com.docker.compose.project=$project" --filter 'label=com.docker.compose.service=sentinel-1' -q)" ]]; then
    echo 'Sentinel state exists. Confirm the current primary before switching topology.' >&2
    exit 1
  fi
fi
case "$mode" in
  up)
    "${dc[@]}" build
    if [[ "$sentinel_mode" == 1 ]]; then
      "${dc[@]}" up -d --no-deps sentinel-1 sentinel-2 sentinel-3
      primary=
      for ((attempt=0; attempt<30; attempt++)); do
        primary=$(sentinel_primary)
        [[ -z "$primary" ]] || break
        sleep 1
      done
      case "$primary" in
        "$MALL_REDIS_NETWORK_PREFIX".201) service=redis;;
        "$MALL_REDIS_NETWORK_PREFIX".202) service=redis-replica;;
        "$MALL_REDIS_NETWORK_PREFIX".203) service=redis-replica-2;;
        *) echo 'No Redis Sentinel majority view' >&2; exit 1;;
      esac
      "${dc[@]}" up -d --no-deps --wait --wait-timeout 90 "$service"
    fi
    "${dc[@]}" up -d --wait --wait-timeout 300
    "${dc[@]}" run --rm seed
    ;;
  reconcile)
    redis_args=()
    if [[ "$sentinel_mode" == 1 ]]; then
      primary=$(sentinel_primary)
      [[ -n "$primary" ]] || { echo 'No Redis Sentinel majority view' >&2; exit 1; }
      redis_args=(-e "MALL_REDIS_URL=redis://$primary:6379/0")
    fi
    "${dc[@]}" run --rm --no-deps -T "${redis_args[@]}" migrate python scripts/reconcile.py "${@:2}"
    ;;
  build) "${dc[@]}" build;;
  seed) "${dc[@]}" run --rm seed;;
  renew-demo) "${dc[@]}" run --rm seed python scripts/renew-demo.py;;
  down) "${dc[@]}" down;;
  status) "${dc[@]}" ps -a;;
  logs) "${dc[@]}" logs --tail 100;;
  *) echo 'Usage: bash scripts/stack.sh [up|build|seed|renew-demo|reconcile|down|status|logs]' >&2; exit 2;;
esac
