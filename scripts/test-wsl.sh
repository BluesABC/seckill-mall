#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
source scripts/env-wsl.sh
mode="${1:---all}"
if [[ $# -gt 1 || ( "$mode" != --cpp && "$mode" != --all ) ]]; then
  echo 'Usage: bash scripts/test-wsl.sh [--cpp|--all]' >&2
  exit 2
fi
if [[ "$(uname -s)" != Linux ]]; then
  echo 'Run inside WSL/Linux, not Windows Git Bash.' >&2
  exit 2
fi
report_dir="$project_root/tests/reports/wsl"
mkdir -p "$report_dir" "$project_root/build/wsl"
report="$report_dir/s0-${mode#--}.log"
exec > >(tee "$report") 2>&1
trap 'result=$?; echo "ExitCode=$result; report=$report"' EXIT
echo "Mode=$mode; root=$project_root; date=$(date -u +%FT%TZ)"
required=(cmake c++ python3)
if [[ "$mode" == --all ]]; then required+=(java mvn node npm docker); fi
missing=0
for tool in "${required[@]}"; do
  tool_path="$(command -v "$tool" || true)"
  if [[ -z "$tool_path" ]]; then
    echo "Missing Linux tool: $tool (see docs/TESTING.md)" >&2; missing=1
  elif [[ "$tool_path" == /mnt/[a-z]/Program\ Files/* || "$tool_path" == /mnt/[a-z]/Users/*/AppData/* || "$tool_path" == *.exe || "$tool_path" == *.cmd ]]; then
    echo "Windows tool rejected: $tool_path; install native Linux $tool" >&2; missing=1
  fi
done
if [[ "$missing" == 1 ]]; then exit 2; fi
cat /etc/os-release
cmake --version | head -n 1
c++ --version | head -n 1
python3 --version
cmake -S "$project_root" -B "$project_root/build/wsl/cpp" -DBUILD_TESTING=ON -DCMAKE_BUILD_TYPE=Release
cmake --build "$project_root/build/wsl/cpp" -j2
ctest --test-dir "$project_root/build/wsl/cpp" --output-on-failure
if [[ "$mode" == --cpp ]]; then
  echo 'PASS: C++ subset only; Java/Vue/contracts/Compose NOT RUN.'
  exit 0
fi
java -version
mvn --version
node --version
npm --version
py="$project_root/build/wsl/venv/bin/python"
if [[ ! -x "$py" ]] || ! "$py" -m pip --version >/dev/null 2>&1; then
  python3 -m venv --copies "$project_root/build/wsl/venv"
fi
"$py" -m pip install -r scripts/requirements-validation.txt
"$py" scripts/verify_contracts.py
mvn -f src/order/pom.xml -Dmall.build.directory="$project_root/build/wsl/order-target" -B verify
ORDER_JAR="$project_root/build/wsl/order-target/order-service-0.1.0-SNAPSHOT.jar" "$py" scripts/smoke_order.py
# Separate workspace: native Node packages must not overwrite Windows node_modules.
mkdir -p build/wsl/web
cp src/web/package.json src/web/package-lock.json src/web/tsconfig.json src/web/vite.config.ts src/web/index.html build/wsl/web/
cp -R src/web/src src/web/public build/wsl/web/
(cd build/wsl/web && npm ci --no-audit --no-fund && npm run build)
docker compose --env-file deploy/.env.example -f deploy/compose.infra.yml config --quiet
echo 'PASS: S0 WSL skeleton checks. Real Redis/MySQL/MQ and business tests NOT RUN.'
