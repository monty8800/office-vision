"""在线升级：从 GitHub Releases 检查新版本、下载平台资产、自替换并重启。

资产约定（由 CI 打包上传，两平台均为 zip）：
- macOS:   office-vision-tray-darwin.zip（Office Vision Tray.app + config.yaml）
- Windows: office-vision-tray-windows.zip（onedir 目录 + config.yaml）

升级时只替换应用本体，不覆盖用户已修改的 config.yaml（安装模式下配置在用户目录，天然不受影响）。
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests

from . import __version__

_API = "https://api.github.com"
_IS_WINDOWS = sys.platform == "win32"


class UpdateError(Exception):
    """升级流程中的可预期错误（网络、资产缺失等）。"""


@dataclass(frozen=True)
class Release:
    tag: str
    name: str
    body: str
    asset_url: str  # API 资产地址（带 token 可下载私有仓库附件）
    asset_size: int


def current_version() -> str:
    return __version__


def _parse_version(tag: str) -> tuple[int, ...]:
    parts = []
    for piece in tag.lstrip("vV").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _headers(token: str) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "office-vision-tray"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _expected_asset_name() -> str:
    """按当前平台推导资产名，与 config.yaml 的 asset_pattern 保持一致。"""
    os_name = "windows" if _IS_WINDOWS else "darwin"
    return f"office-vision-tray-{os_name}.zip"


def fetch_latest_release(repo: str, token: str, asset_pattern: str) -> Release | None:
    """拉取最新 Release；无 Release 或无匹配资产返回 None。"""
    url = f"{_API}/repos/{repo}/releases/latest"
    resp = requests.get(url, headers=_headers(token), timeout=15)
    if resp.status_code == 404:
        return None  # 仓库尚无 Release
    if resp.status_code != 200:
        raise UpdateError(f"GitHub API 返回 {resp.status_code}（私有仓库需配置 OVA_GITHUB_TOKEN）")

    data = resp.json()
    os_name = "windows" if _IS_WINDOWS else "darwin"
    wanted = asset_pattern.format(os=os_name)
    for asset in data.get("assets", []):
        if asset["name"] == wanted:
            return Release(
                tag=data["tag_name"],
                name=data.get("name", data["tag_name"]),
                body=data.get("body", "") or "",
                asset_url=asset["url"],
                asset_size=int(asset.get("size", 0)),
            )
    raise UpdateError(f"Release {data['tag_name']} 缺少当前平台的资产：{wanted}")


def has_update(release: Release) -> bool:
    return _parse_version(release.tag) > _parse_version(current_version())


def download_asset(release: Release, token: str) -> Path:
    """流式下载资产到临时目录，返回文件路径。"""
    headers = _headers(token)
    headers["Accept"] = "application/octet-stream"  # API 资产地址需此 Accept 才返回二进制
    with requests.get(release.asset_url, headers=headers, stream=True, timeout=30) as resp:
        if resp.status_code != 200:
            raise UpdateError(f"资产下载失败：HTTP {resp.status_code}")
        tmp_dir = Path(tempfile.mkdtemp(prefix="ov-tray-update-"))
        dest = tmp_dir / (_expected_asset_name())
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                fh.write(chunk)
    if dest.stat().st_size == 0:
        raise UpdateError("下载文件为空，请检查网络后重试")
    return dest


def apply_update(asset_path: Path) -> str:
    """用下载好的新版本替换当前应用并重启，返回给用户的提示。

    源码运行模式（未打包）无法自替换，提示手动更新；打包模式解压后只替换
    应用本体（config.yaml 不动，保留用户修改），由外部脚本在退出后完成替换。
    """
    if not getattr(sys, "frozen", False):
        return f"新版本已下载（{asset_path}），源码运行模式请 git pull 后重启应用"
    extract_dir = asset_path.parent / "extracted"
    with zipfile.ZipFile(asset_path) as zf:
        zf.extractall(extract_dir)
    if _IS_WINDOWS:
        # 新版 zip 为 onedir 目录：找包含 exe 的顶层目录做整目录替换
        app_dirs = [p for p in extract_dir.iterdir() if p.is_dir() and any(p.rglob("*.exe"))]
        if not app_dirs:
            raise UpdateError("压缩包内未找到应用目录")
        _apply_windows(app_dirs[0])
    else:
        apps = list(extract_dir.glob("*.app"))
        if not apps:
            raise UpdateError("压缩包内未找到 .app")
        _apply_macos(apps[0])
    return "升级完成，应用即将重启"


def _apply_windows(new_dir: Path) -> None:
    """整目录替换：等当前进程退出后 robocopy /MIR 覆盖安装目录再拉起。"""
    current_exe = Path(sys.executable)
    install_dir = current_exe.parent
    script = f"""@echo off
:wait
tasklist /FI "PID eq {os.getpid()}" | find "{os.getpid()}" >nul && (timeout /t 1 >nul & goto wait)
robocopy "{new_dir}" "{install_dir}" /MIR /NFL /NDL /NJH /NJS >nul
start "" "{current_exe}"
"""
    bat = new_dir.parent / "apply_update.bat"
    bat.write_text(script, encoding="ascii", errors="ignore")
    flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=flags, close_fds=True)


def _apply_macos(new_app: Path) -> None:
    # 当前可执行文件位于 Contents/MacOS/内，向上三级即 .app 目录
    current_app = Path(sys.executable).resolve().parent.parent.parent
    if current_app.suffix != ".app":
        raise UpdateError(f"无法定位当前 .app 目录：{current_app}")

    script = f"""#!/bin/sh
while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.5; done
rm -rf "{current_app}"
mv "{new_app}" "{current_app}"
open "{current_app}"
"""
    sh = new_app.parent / "apply_update.sh"
    sh.write_text(script, encoding="utf-8")
    sh.chmod(sh.stat().st_mode | stat.S_IXUSR)
    subprocess.Popen(["/bin/sh", str(sh)], start_new_session=True, stdout=subprocess.DEVNULL)


def cleanup_temp(asset_path: Path) -> None:
    shutil.rmtree(asset_path.parent, ignore_errors=True)
