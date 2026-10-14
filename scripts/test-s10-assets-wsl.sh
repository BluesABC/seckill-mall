#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
source scripts/env-wsl.sh
[[ "$(uname -s)" == Linux && "$(command -v python3)" != *.exe ]] || { echo 'Run inside WSL/Linux with native Python'; exit 2; }
mkdir -p tests/reports/wsl
exec > >(tee tests/reports/wsl/s10-assets-run.log) 2>&1
trap 'result=$?; echo "ExitCode=$result"' EXIT
cat /etc/os-release
uname -r
python3 --version
py="$root/build/wsl/venv/bin/python"
[[ -x "$py" ]] || { python3 -m venv --copies "$root/build/wsl/venv"; }
"$py" -m pip install -r scripts/requirements-assets.txt
"$py" scripts/optimize-storefront-images.py
"$py" scripts/optimize-storefront-images.py --check
python3 - <<'PY'
from pathlib import Path
root = Path("src/web/public/assets")
expected = {"sports-hero-v1.webp", "shoe-run-v1.webp", "shoe-court-v1.webp", "shoe-street-v1.webp"}
actual = {p.name for p in root.glob("*") if p.is_file()}
assert actual == expected, f"unexpected published assets: {actual ^ expected}"
for name in sorted(expected):
    size = (root / name).stat().st_size
    assert size < 500_000, f"{name} exceeds 500 KB: {size}"
    print(f"PASS {name}: {size} bytes")
PY
