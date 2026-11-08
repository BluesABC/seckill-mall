#!/usr/bin/env bash
# 职责：在指定Compose工具容器中运行只读对账；输出诊断，不清理库存或业务卷。
# 运行口径与所需环境见 docs/TESTING.md；代码阅读导航见 docs/CODE-READING.md。
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)";cd "$root"
exec bash "$root/scripts/stack.sh" reconcile "$@"
