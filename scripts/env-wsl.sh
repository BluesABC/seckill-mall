#!/usr/bin/env bash
# 职责：给当前shell注入项目内Linux Node路径；必须source，不借用Windows可执行文件。
# 运行口径与所需环境见 docs/TESTING.md；代码阅读导航见 docs/CODE-READING.md。
# source scripts/env-wsl.sh; installed Node stays project-local.
mall_project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mall_node_dir="$mall_project_root/build/wsl/tooling/node-v22.20.0-linux-x64/bin"
if [[ -x "$mall_node_dir/node" ]]; then export PATH="$mall_node_dir:$PATH"; fi
unset mall_node_dir mall_project_root
