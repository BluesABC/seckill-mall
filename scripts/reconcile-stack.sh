#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)";cd "$root"
docker compose -p "${MALL_STACK_PROJECT:-seckill-mall-stack}" --env-file "${MALL_STACK_ENV:-$root/deploy/.env.stack}" -f "$root/deploy/compose.yml" run --rm --no-deps -T migrate python scripts/reconcile.py "$@"
