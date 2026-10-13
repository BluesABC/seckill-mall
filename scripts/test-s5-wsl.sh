#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
source scripts/env-wsl.sh
mkdir -p tests/reports/wsl build/wsl/browser
exec > >(tee tests/reports/wsl/s5-run.log) 2>&1
trap 'result=$?; echo "ExitCode=$result"' EXIT
cat /etc/os-release
uname -r
node --version
java -version
docker version --format '{{.Server.Version}}'
mvn -B -f src/order/pom.xml -Dmall.build.directory="$root/build/wsl/order-target" verify
bash scripts/build-web-wsl.sh
cp tests/browser/package.json tests/browser/package-lock.json build/wsl/browser/
(cd build/wsl/browser && npm ci --no-audit --no-fund && npx playwright install chromium)
build/wsl/venv/bin/python scripts/storefront_runtime.py --test
