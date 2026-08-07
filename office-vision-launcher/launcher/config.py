"""托盘应用配置加载：config.yaml 为唯一配置源，环境变量仅做覆盖。

找不到 config.yaml 时自动生成默认配置（首次部署免手工初始化）。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

# 首次启动且 config.yaml 缺失时写入的默认配置（与仓库 config.yaml 保持同步）
DEFAULT_CONFIG_YAML = """\
# Office Vision Agent 托盘应用配置（首次启动自动生成）
# 托盘仅托管 Agent；Server / Dashboard 不在托管范围。

github_repo: "monty8800/office-vision"
github_token: ""
asset_pattern: "office-vision-tray-{os}.zip"

server_url: "http://localhost:8000"

services:
  - name: agent
    label: "Agent"
    port: 8100
    workdir: "../office-vision-agent"
    command: ["uv", "run", "python", "-m", "agent.main"]

restart_delay_seconds: 3

dashboard_url: "http://localhost:3000"
"""


@dataclass(frozen=True)
class ServiceSpec:
    """受管服务定义（当前仅 Agent）。"""

    name: str
    label: str
    port: int
    workdir: Path
    command: tuple[str, ...]


@dataclass(frozen=True)
class AppConfig:
    github_repo: str
    github_token: str
    asset_pattern: str
    server_url: str
    services: list[ServiceSpec]
    restart_delay_seconds: float
    dashboard_url: str


def app_base_dir() -> Path:
    """部署根目录（config.yaml / data/logs 所在层级）：
    macOS 冻结模式从 Contents/MacOS 逐级向上 4 级到 .app 旁，
    Windows 冻结模式取 exe 所在目录，开发模式取子项目根目录。"""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        base = exe.parent.parent.parent.parent if sys.platform == "darwin" else exe.parent
        return base
    return Path(__file__).resolve().parent.parent


def _candidate_dirs() -> list[Path]:
    """config.yaml 搜索路径：打包模式从可执行文件逐级向上找（适配 .app 层级与部署目录），
    开发模式取子项目根目录。"""
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        # macOS: Contents/MacOS/exe → 逐级向上，依次命中 .app 内、.app 旁（部署目录）
        # Windows: exe 所在目录即部署目录
        current = Path(sys.executable).resolve().parent
        for _ in range(4):
            dirs.append(current)
            current = current.parent
    dirs.append(Path(__file__).resolve().parent.parent)  # 开发模式：office-vision-launcher/
    return dirs


def _app_support_dir() -> Path:
    """用户级配置目录（部署目录不可写时的兜底，如直接从 DMG 卷内运行）。"""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / "Library" / "Application Support"
    return base / "Office Vision Tray"


def _create_default_config() -> Path:
    """生成默认 config.yaml：优先部署目录（倒序尝试，避开 .app 内部），
    全部不可写（如只读 DMG 卷）则落到用户配置目录。"""
    candidates = [*reversed(_candidate_dirs()), _app_support_dir()]
    last_error: Exception | None = None
    for base in candidates:
        path = base / "config.yaml"
        try:
            base.mkdir(parents=True, exist_ok=True)
            path.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")
            return path
        except OSError as exc:
            last_error = exc
    raise FileNotFoundError(f"无法创建默认 config.yaml：{last_error}")


def config_path() -> Path:
    for base in _candidate_dirs():
        path = base / "config.yaml"
        if path.is_file():
            return path
    return _create_default_config()


def load_config() -> AppConfig:
    raw = yaml.safe_load(config_path().read_text(encoding="utf-8"))
    workdir_base = config_path().parent

    services = [
        ServiceSpec(
            name=item["name"],
            label=item.get("label", item["name"]),
            port=int(item["port"]),
            workdir=(workdir_base / item["workdir"]).resolve(),
            command=tuple(item["command"]),
        )
        for item in raw["services"]
    ]

    return AppConfig(
        github_repo=os.environ.get("OVA_GITHUB_REPO", raw["github_repo"]),
        github_token=os.environ.get("OVA_GITHUB_TOKEN", raw.get("github_token") or ""),
        asset_pattern=raw["asset_pattern"],
        server_url=os.environ.get("OVA_SERVER_URL", raw.get("server_url", "http://localhost:8000")),
        services=services,
        restart_delay_seconds=float(raw.get("restart_delay_seconds", 3)),
        dashboard_url=os.environ.get("OVA_DASHBOARD_URL", raw["dashboard_url"]),
    )
