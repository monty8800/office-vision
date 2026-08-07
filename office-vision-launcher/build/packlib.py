"""平台打包脚本共享逻辑：PyInstaller 编译、zip 自更新资产、DMG 安装包、Windows 安装器。

RFC-0008：build/ 目录负责平台打包，GitHub Actions 仅调用对应脚本。
产物统一输出到 dist/：
- office-vision-tray-{os}.zip        自更新资产（应用本体 + config.yaml）
- OfficeVisionLauncher-macOS.dmg     人工安装包（macOS，拖入应用程序文件夹）
- OfficeVisionTray-Windows-Setup.exe 安装器（Windows，Inno Setup）
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
STAGE = DIST / "stage"  # PyInstaller 输出暂存区
APP_NAME = "Office Vision Tray"
IS_WINDOWS = sys.platform == "win32"
OS_NAME = "windows" if IS_WINDOWS else "darwin"


def _patch_macos_plist() -> None:
    """补全 Info.plist：规范 Bundle ID（TCC 权限注册必需，否则应用不出现在
    摄像头授权列表）+ 摄像头用途说明（缺失时系统直接拒绝弹窗）。"""
    app = STAGE / f"{APP_NAME}.app"
    plist_path = app / "Contents" / "Info.plist"
    with plist_path.open("rb") as fh:
        plist = plistlib.load(fh)
    plist["CFBundleIdentifier"] = "com.monty8800.office-vision-tray"
    plist["NSCameraUsageDescription"] = "需要摄像头画面用于办公行为分析（在岗检测、抽烟检测等）"
    with plist_path.open("wb") as fh:
        plistlib.dump(plist, fh)
    # 清理扩展属性（否则 codesign 报 resource fork detritus），
    # 修改 plist 也会使原 ad-hoc 签名失效，需重新签名
    subprocess.run(["xattr", "-cr", str(app)], check=True, capture_output=True)
    subprocess.run(
        ["codesign", "--force", "--deep", "-s", "-", str(app)],
        check=True, capture_output=True,
    )


def pyinstaller_build() -> None:
    """PyInstaller 编译到 STAGE（macOS 出 .app bundle，Windows 出 onedir 目录供安装器打包）。"""
    shutil.rmtree(DIST, ignore_errors=True)
    STAGE.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--distpath", str(STAGE),
        "--workpath", str(DIST / "work"),  # 中间产物避开 build/ 脚本目录
        "--noconfirm",
        "--clean",
        # pystray 各平台后端（AppKit/win32）为动态导入，需整包收集避免打包后缺失
        "--collect-all", "pystray",
        # 入口用包根 __main__.py（非 launcher/main.py），否则 PyInstaller 下相对导入会失败
        str(ROOT / "__main__.py"),
    ]
    cmd += ["--noconsole"] if IS_WINDOWS else ["--windowed"]
    subprocess.run(cmd, cwd=ROOT, check=True)
    if not IS_WINDOWS:
        # --windowed 会同时残留 onedir 目录，仅保留 .app bundle
        shutil.rmtree(STAGE / APP_NAME, ignore_errors=True)
        _patch_macos_plist()
    # 配置随产物分发：便携用户可直接使用；安装模式下应用会在用户目录自动生成配置
    shutil.copy(ROOT / "config.yaml", STAGE / "config.yaml")


def make_zip() -> Path:
    """自更新资产：zip = 应用本体 + config.yaml。"""
    asset = DIST / f"office-vision-tray-{OS_NAME}.zip"
    with zipfile.ZipFile(asset, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in STAGE.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(STAGE))
    return asset


def make_installer() -> Path:
    """Windows 安装器：Inno Setup 把 onedir 产物打成 Setup.exe（当前用户级安装，无 UAC）。"""
    if not IS_WINDOWS:
        raise RuntimeError("Setup.exe 仅支持 Windows")
    iscc = Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")
    if not iscc.is_file():
        found = shutil.which("iscc")
        if not found:
            raise RuntimeError("未找到 Inno Setup（ISCC.exe）")
        iscc = Path(found)
    subprocess.run([str(iscc), str(ROOT / "build" / "installer.iss")], cwd=ROOT, check=True)
    return DIST / "OfficeVisionTray-Windows-Setup.exe"


def make_dmg() -> Path:
    """人工安装包：hdiutil 生成 DMG（macOS 原生工具，CI runner 自带）。"""
    if IS_WINDOWS:
        raise RuntimeError("DMG 仅支持 macOS")
    app_dir = STAGE / f"{APP_NAME}.app"
    dmg = DIST / "OfficeVisionLauncher-macOS.dmg"
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "dmg-src"
        src.mkdir()
        shutil.copytree(app_dir, src / f"{APP_NAME}.app", symlinks=True)
        # 放入 Applications 替身：打开 DMG 即呈现经典"拖入应用程序文件夹"画面，
        # 否则用户双击 App 只是从挂载卷临时运行，不会出现在"应用程序"列表
        (src / "Applications").symlink_to("/Applications")
        # 配置文件随 DMG 分发，用户可将两者一起拷入部署目录；
        # 即使不拷，应用也会自动生成默认配置
        shutil.copy(STAGE / "config.yaml", src / "config.yaml")
        subprocess.run(
            ["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", str(src),
             "-ov", "-format", "UDZO", str(dmg)],
            check=True, capture_output=True,
        )
    return dmg
