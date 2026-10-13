#!/usr/bin/env bash
# source scripts/env-wsl.sh; installed Node stays project-local.
mall_project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mall_node_dir="$mall_project_root/build/wsl/tooling/node-v22.20.0-linux-x64/bin"
if [[ -x "$mall_node_dir/node" ]]; then export PATH="$mall_node_dir:$PATH"; fi
unset mall_node_dir mall_project_root
