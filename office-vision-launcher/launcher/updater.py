"""在线升级：从 GitHub Releases 检查新版本、下载平台资产、自替换并重启。

检查更新走 releases.atom 订阅源（不经 api.github.com）：
未认证 API 每 IP 每小时仅 60 次，共享出口 IP 极易触发 403 限流；
atom 源无此限制，资产下载链接可由 tag 直接推导。

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
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

import requests

from . import __version__

_IS_WINDOWS = sys.platform == "win32"
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


class UpdateError(Exception):
    """升级流程中的可预期错误（网络、资产缺失等）。"""


@dataclass(frozen=True)
class Release:
    tag: str
    name: str
    body: str
    asset_url: str  # 资产直链（公开仓库无需 token）
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


def _fetch_atom(repo: str, token: str, asset_pattern: str) -> Release | None:
    """从 releases.atom 取最新 Release（无 API 限流）；无 Release 返回 None。"""
    url = f"https://github.com/{repo}/releases.atom"
    try:
        resp = requests.get(url, headers=_headers(token), timeout=(5, 15))
    except requests.RequestException as exc:
        raise UpdateError(f"连接 GitHub 失败：{exc}") from exc
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise UpdateError(f"GitHub 返回 {resp.status_code}")
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        raise UpdateError(f"releases.atom 解析失败：{exc}") from exc
    entry = root.find(f"{_ATOM_NS}entry")
    if entry is None:
        return None  # 仓库尚无 Release
    # entry id 形如 tag:github.com,2008:Repository/123456/v0.2.1，末段即 tag
    entry_id = entry.findtext(f"{_ATOM_NS}id", default="")
    tag = entry_id.rsplit("/", 1)[-1]
    if not tag:
        raise UpdateError("releases.atom 缺少版本号")
    asset = asset_pattern.format(os="windows" if _IS_WINDOWS else "darwin")
    return Release(
        tag=tag,
        name=entry.findtext(f"{_ATOM_NS}title", default=tag) or tag,
        body=entry.findtext(f"{_ATOM_NS}content", default="") or "",
        # 资产直链由 tag 推导，不经 API；下载时自动跟随重定向到 CDN
        asset_url=f"https://github.com/{repo}/releases/download/{tag}/{asset}",
        asset_size=0,
    )


def _fetch_api(repo: str, token: str, asset_pattern: str) -> Release | None:
    """API 兑底：仅在配置了 token 且 atom 不可用时走（认证后限额 5000/小时）。"""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        resp = requests.get(url, headers=_headers(token), timeout=(5, 15))
    except requests.RequestException as exc:
        raise UpdateError(f"连接 GitHub 失败：{exc}") from exc
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise UpdateError(f"GitHub API 返回 {resp.status_code}")

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


def fetch_latest_release(repo: str, token: str, asset_pattern: str) -> Release | None:
    """拉取最新 Release：优先 atom 订阅源（避开未认证 API 限流），
    atom 异常且配置了 token 时回退到 API；无 Release 返回 None。"""
    try:
        release = _fetch_atom(repo, token, asset_pattern)
    except UpdateError:
        if not token:
            raise
    else:
        # atom 可达即为准（含无 Release 的情况），不再查 API
        return release
    return _fetch_api(repo, token, asset_pattern)


def has_update(release: Release) -> bool:
    return _parse_version(release.tag) > _parse_version(current_version())


def download_asset(release: Release, token: str) -> Path:
    """流式下载资产到临时目录，返回文件路径。"""
    headers = _headers(token)
    # API 资产地址需此 Accept 才返回二进制；直链不受影响
    headers["Accept"] = "application/octet-stream"
    try:
        with requests.get(release.asset_url, headers=headers, stream=True,
                          timeout=(10, 60)) as resp:
            if resp.status_code != 200:
                raise UpdateError(f"资产下载失败：HTTP {resp.status_code}")
            tmp_dir = Path(tempfile.mkdtemp(prefix="ov-tray-update-"))
            dest = tmp_dir / (_expected_asset_name())
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    fh.write(chunk)
    except requests.RequestException as exc:
        raise UpdateError(f"资产下载失败：{exc}") from exc
    if dest.stat().st_size == 0:
        raise UpdateError("下载文件为空，请检查网络后重试")
    return dest


def _restore_unix_modes(zf: zipfile.ZipFile, extract_dir: Path) -> None:
    """zipfile.extractall 不恢复 Unix 权限（可执行位丢失），按 zip 元数据补回。
    macOS 主可执行文件失 +x 后系统直接报"应用程序无法打开"，自更新必挂。"""
    for info in zf.infolist():
        mode = (info.external_attr >> 16) & 0o7777
        if not mode or info.is_dir():
            continue
        target = extract_dir / info.filename
        if target.is_file():
            target.chmod(mode)


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
        _restore_unix_modes(zf, extract_dir)
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
