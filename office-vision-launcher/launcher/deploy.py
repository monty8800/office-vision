"""首次部署自动化：托盘检测到 Agent 环境缺失时，自动完成
克隆仓库 → 安装 uv → 安装依赖 → 下载基础模型，macOS / Windows 双平台。

新监控设备只需下载托盘应用并启动，无需手动执行任何命令。
目录约定：仓库克隆到托盘目录的上级（与 office-vision-agent 平级），
与 config.yaml 的 workdir 相对路径 "../office-vision-agent" 保持一致。
只检出 office-vision-agent（sparse-checkout）：托盘仅托管 Agent，
Server/Dashboard/训练目录不应占用监控设备磁盘。
模型文件（models/*.pt、*.task）已随仓库分发，检出即就位；
下载脚本仅在文件缺失时兜底（避免依赖境外存储导致部署卡死）。
所有外部命令均带超时，弱网环境下会明确报错而非无限挂起。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_IS_WINDOWS = sys.platform == "win32"


class DeployError(RuntimeError):
    """部署步骤失败（错误信息会展示在托盘菜单）。"""


def agent_deployed(agent_workdir: Path) -> bool:
    """环境就绪判定：Agent 配置存在即认为已部署（依赖/模型缺失由 uv run 自愈）。"""
    return (agent_workdir / "config" / "agent.yaml").is_file()


def build_clone_url(repo: str, token: str) -> str:
    """构建克隆地址：传入 token 时内嵌认证（仓库为私有时必需）。"""
    clean = repo.removeprefix("https://github.com/").removesuffix(".git")
    if token:
        return f"https://x-access-token:{token}@github.com/{clean}.git"
    return f"https://github.com/{clean}.git"


def mask_url(text: str) -> str:
    """错误提示中抹掉内嵌 token，避免泄露到菜单/日志。"""
    if "://" in text:
        prefix, rest = text.split("://", 1)
        if "@" in rest:
            return f"{prefix}://****@{rest.rsplit('@', 1)[1]}"
    return text


def _run(cmd: list[str], cwd: Path | None = None, timeout: float = 600.0) -> None:
    """执行外部命令：超时后明确报错（弱网环境下无超时会无限挂起，
    托盘将永远停在“正在部署环境”）。"""
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise DeployError(
            f"命令超时（{timeout:.0f} 秒）：{' '.join(cmd[:2])}，请检查网络后重试"
        ) from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise DeployError(detail[-1] if detail else f"命令失败：{' '.join(cmd[:2])}")


def _uv_path() -> str | None:
    """定位 uv：PATH 优先，其次各平台默认安装位置（刚装完的 uv 不在当前进程 PATH 里）。"""
    found = shutil.which("uv")
    if found:
        return found
    candidates = (
        (Path.home() / "AppData" / "Roaming" / "uv" / "uv.exe",)
        if _IS_WINDOWS
        else (Path.home() / ".local" / "bin" / "uv",)
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _ensure_uv() -> str:
    """确保 uv 可用，缺失则通过官方脚本安装（macOS: curl / Windows: PowerShell）。"""
    uv = _uv_path()
    if uv:
        return uv
    try:
        if _IS_WINDOWS:
            _run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "ByPass",
                    "-Command",
                    "irm https://astral.sh/uv/install.ps1 | iex",
                ],
                timeout=300,
            )
        else:
            _run(
                ["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"], timeout=300
            )
    except DeployError:
        raise DeployError("uv 安装失败（请检查网络）") from None
    uv = _uv_path()
    if uv is None:
        raise DeployError("uv 安装后未找到可执行文件，请重新打开托盘")
    return uv


def _git(root: Path, *args: str, timeout: float = 600.0) -> None:
    _run(["git", "-C", str(root), *args], timeout=timeout)


# 只检出 Agent 运行所需目录：agent 本体 + 自训练香烟检测权重
# （agent.yaml 的 cigarette_weights 指向 ../yolo-training/weights/，缺失会降级为仅人形检测）
_SPARSE_PATHS = ("office-vision-agent", "yolo-training/weights")


def _clone_repo(repo: str, token: str, repo_root: Path) -> None:
    """把仓库检出到 repo_root（可能已存在托盘目录，故用 init+fetch 而非 clone）。

    sparse-checkout 只检出 Agent 所需目录：对已全量检出的旧部署，
    重新应用规则 + checkout 会自动清掉其余子项目目录。
    """
    url = build_clone_url(repo, token)
    try:
        if not (repo_root / ".git").exists():
            _run(["git", "init", str(repo_root)])
            _git(repo_root, "remote", "add", "origin", url)
        else:
            _git(repo_root, "remote", "set-url", "origin", url)
        _git(repo_root, "sparse-checkout", "set", "--cone", *_SPARSE_PATHS)
        _git(repo_root, "fetch", "--depth", "1", "origin", "HEAD", timeout=900)
        _git(repo_root, "checkout", "-f", "FETCH_HEAD")
    except FileNotFoundError:
        raise DeployError("未找到 git（macOS 可执行 xcode-select --install 安装）") from None
    except DeployError as exc:
        message = str(exc)
        if "Authentication" in message or "could not read Username" in message:
            raise DeployError("仓库为私有：请在 config.yaml 填写 github_token 后重试") from None
        raise DeployError(mask_url(message)) from None


def _install_deps(uv: str, agent_workdir: Path) -> None:
    try:
        _run([uv, "sync"], cwd=agent_workdir, timeout=1200)
    except DeployError as exc:
        raise DeployError(f"依赖安装失败：{exc}") from exc


def _download_models(uv: str, agent_workdir: Path) -> None:
    # 模型已随仓库分发（检出即就位），脚本检测存在会直接跳过，
    # 此步仅作为缺失时的兜底下载
    try:
        _run([uv, "run", "python", "scripts/download_models.py"], cwd=agent_workdir, timeout=600)
    except DeployError as exc:
        raise DeployError(f"模型下载失败：{exc}") from exc


class Deployer:
    """部署编排：顺序执行各步骤，on_step 回调把当前步骤文案推给托盘菜单。"""

    def __init__(self, repo: str, token: str, agent_workdir: Path):
        self.repo = repo
        self.token = token
        self.agent_workdir = agent_workdir
        self.repo_root = agent_workdir.parent

    def run(self, on_step: object = None) -> None:
        def step(label: str) -> None:
            if callable(on_step):
                on_step(label)

        step("检查 uv 环境")
        uv = _ensure_uv()
        if not agent_deployed(self.agent_workdir):
            step("克隆仓库（仅 Agent 目录）")
            _clone_repo(self.repo, self.token, self.repo_root)
        step("安装依赖（约 1~3 分钟）")
        _install_deps(uv, self.agent_workdir)
        step("下载基础模型")
        _download_models(uv, self.agent_workdir)
