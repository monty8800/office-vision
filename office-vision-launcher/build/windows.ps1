# RFC-0008：Windows 平台打包脚本。本地与 GitHub Actions 共用，workflow 只调用本脚本。
# 前置：uv 已安装；安装器依赖 Inno Setup 6（CI runner 自带）。
# 产物（dist/）：
#   office-vision-tray-windows.zip        自更新资产（onedir 目录 + config.yaml）
#   OfficeVisionTray-Windows-Setup.exe    安装器（当前用户级安装，首次启动自动下载依赖）
# 注：CI 的 Windows 控制台为 cp1252 编码，Python 输出禁止使用中文（UnicodeEncodeError）。
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

uv sync --group dev
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

uv run --group dev python -c "from build.packlib import make_installer, make_zip, pyinstaller_build; pyinstaller_build(); print('zip asset:', make_zip()); print('installer:', make_installer())"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
