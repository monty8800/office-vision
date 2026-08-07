#!/bin/sh
# RFC-0008：macOS 平台打包脚本。本地与 GitHub Actions 共用，workflow 只调用本脚本。
# 前置：uv 已安装（uv sync --group dev 由调用方或本脚本完成）。
# 产物（dist/）：
#   office-vision-tray-darwin.zip      自更新资产（.app + config.yaml）
#   OfficeVisionLauncher-macOS.dmg     人工安装包
set -eu
cd "$(dirname "$0")/.."

uv sync --group dev
uv run --group dev python - <<'EOF'
from build.packlib import make_dmg, make_zip, pyinstaller_build

pyinstaller_build()
print("自更新资产:", make_zip())
print("安装包:", make_dmg())
EOF
