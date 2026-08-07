# RFC-0008：Windows 平台打包脚本。本地与 GitHub Actions 共用，workflow 只调用本脚本。
# 前置：uv 已安装。
# 产物（dist/）：
#   office-vision-tray-windows.zip     自更新资产（exe + config.yaml）
#   OfficeVisionLauncher-Windows.exe   便携版单文件
# 注：Setup.exe（Inno Setup）为后续迭代，见 README 路线图。
# 注：CI 的 Windows 控制台为 cp1252 编码，Python 输出禁止使用中文（UnicodeEncodeError）。
$ErrorActionPreference = "Stop"
Set-Location "$PSScriptRoot\.."

uv sync --group dev
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

uv run --group dev python -c "from build.packlib import make_exe, make_zip, pyinstaller_build; pyinstaller_build(); print('zip asset:', make_zip()); print('portable exe:', make_exe())"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
