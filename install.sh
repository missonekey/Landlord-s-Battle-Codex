#!/usr/bin/env bash
# 斗地主 Codex 插件安装脚本
set -euo pipefail
cd "$(dirname "$0")"
exec python3 install_plugin.py
