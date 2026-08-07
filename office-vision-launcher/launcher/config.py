"""托盘应用配置加载：config.yaml 为唯一配置源，环境变量仅做覆盖。"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


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
    services: list[ServiceSpec]
    restart_delay_seconds: float
    dashboard_url: str


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


def config_path() -> Path:
    for base in _candidate_dirs():
        path = base / "config.yaml"
        if path.is_file():
            return path
    raise FileNotFoundError("找不到 config.yaml，请确认其位于托盘应用目录")


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
        services=services,
        restart_delay_seconds=float(raw.get("restart_delay_seconds", 3)),
        dashboard_url=os.environ.get("OVA_DASHBOARD_URL", raw["dashboard_url"]),
    )
