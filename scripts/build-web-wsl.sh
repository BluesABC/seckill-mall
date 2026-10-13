#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
source scripts/env-wsl.sh
[[ "$(uname -s)" == Linux && "$(command -v node)" != *.exe ]] || { echo 'Native Linux Node required' >&2; exit 2; }
mkdir -p build/wsl/web
# Only generated copies inside this known workspace are replaced.
rm -rf -- "$root/build/wsl/web/src" "$root/build/wsl/web/public"
cp src/web/package.json src/web/package-lock.json src/web/tsconfig.json src/web/vite.config.ts src/web/index.html build/wsl/web/
cp -R src/web/src src/web/public build/wsl/web/
(cd build/wsl/web && npm ci --no-audit --no-fund && npm run build)
