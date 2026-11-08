#!/usr/bin/env bash
# 职责：同步64人接入诊断入口；区分内核连接等待、worker排队与handler耗时。
# 运行口径与所需环境见 docs/TESTING.md；代码阅读导航见 docs/CODE-READING.md。
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
[[ "$(uname -s)" == Linux ]] || { echo 'Run in WSL/Linux'; exit 2; }
if [[ "${1:-}" == --check ]]; then
  [[ $# == 2 ]] || exit 2
  exec python3 scripts/check_burst_gate.py "$2"
fi
# The Python entry holds the shared capacity lock and restores exact prior
# worker/queue values and the temporary gateway timing config on exit.
exec python3 tests/test_s20_burst.py "$@"
