#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
mode="${1:-up}"
env_file="${MALL_STACK_ENV:-$root/deploy/.env.stack}"
project="${MALL_STACK_PROJECT:-seckill-mall-stack}"
[[ "$project" =~ ^[a-z0-9][a-z0-9_-]+$ ]] || exit 2
[[ -f "$env_file" ]] || { echo 'Generate credentials: python3 scripts/prepare-deploy.py'; exit 2; }
dc=(docker compose -p "$project" --env-file "$env_file" -f deploy/compose.yml)
"${dc[@]}" config --quiet
case "$mode" in
  up) "${dc[@]}" build; cd "$root"; "${dc[@]}" up -d --wait --wait-timeout 300; cd "$root"; "${dc[@]}" run --rm seed;;
  build) "${dc[@]}" build;;
  seed) "${dc[@]}" run --rm seed;;
  renew-demo) "${dc[@]}" run --rm seed python scripts/renew-demo.py;;
  down) "${dc[@]}" down;;
  status) "${dc[@]}" ps -a;;
  logs) "${dc[@]}" logs --tail 100;;
  *) echo 'Usage: bash scripts/stack.sh [up|build|seed|renew-demo|down|status|logs]' >&2; exit 2;;
esac
