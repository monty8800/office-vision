"""Agent 配置系统。

- YAML 为唯一配置源（config/agent.yaml），禁止硬编码（第四原则）
- 环境变量 OVA_AGENT_CONFIG 可覆盖配置路径（容器化部署）
- 类型化段落 + 原始 dict（供硬件/AI 工厂按需取键，新增键无需改代码）
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from agent.monitor.config import MonitorSettings
from agent.presence.manager import PresenceSettings

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "agent.yaml"


@dataclass(frozen=True)
class AgentSection:
    name: str = "office-vision-agent"
    device_id: str = "agent"
    log_level: str = "INFO"


@dataclass(frozen=True)
class PipelineSection:
    process_fps: float = 10.0
    sleep_fps: float = 0.5


@dataclass(frozen=True)
class ServerSection:
    url: str = "http://localhost:8000"
    push_interval_seconds: float = 5.0
    offline_cache: str = "data/event_cache.db"
    heartbeat_interval_seconds: float = 30.0


@dataclass(frozen=True)
class PluginsSection:
    dir: str = "plugins"


@dataclass(frozen=True)
class AgentConfig:
    """全部配置的聚合视图。"""

    agent: AgentSection = field(default_factory=AgentSection)
    camera: dict[str, Any] = field(default_factory=dict)
    detector: dict[str, Any] = field(default_factory=dict)
    pose: dict[str, Any] = field(default_factory=dict)
    pipeline: PipelineSection = field(default_factory=PipelineSection)
    presence: PresenceSettings = field(default_factory=PresenceSettings)
    server: ServerSection = field(default_factory=ServerSection)
    plugins: PluginsSection = field(default_factory=PluginsSection)
    monitor: MonitorSettings = field(default_factory=MonitorSettings)

    @property
    def camera_type(self) -> str:
        return str(self.camera.get("type", "uvc"))

    @property
    def detector_type(self) -> str:
        return str(self.detector.get("type", "yolo"))

    @property
    def pose_type(self) -> str:
        return str(self.pose.get("type", "mediapipe"))


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key) or {}
    if not isinstance(value, dict):
        msg = f"配置段 {key} 必须是映射"
        raise ValueError(msg)
    return value


def _typed(cls: type[Any], data: dict[str, Any]) -> Any:
    known = {f for f in cls.__dataclass_fields__}  # noqa: C416
    return cls(**{k: v for k, v in data.items() if k in known})


def load_config(path: str | Path | None = None) -> AgentConfig:
    """加载并校验配置文件。"""
    config_path = Path(path or os.environ.get("OVA_AGENT_CONFIG") or DEFAULT_CONFIG_PATH)
    if not config_path.exists():
        msg = f"配置文件不存在: {config_path}（可用 OVA_AGENT_CONFIG 指定）"
        raise FileNotFoundError(msg)
    with config_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        msg = f"配置文件格式错误: {config_path}"
        raise ValueError(msg)
    return AgentConfig(
        agent=_typed(AgentSection, _section(raw, "agent")),
        camera=_section(raw, "camera"),
        detector=_section(raw, "detector"),
        pose=_section(raw, "pose"),
        pipeline=_typed(PipelineSection, _section(raw, "pipeline")),
        presence=_typed(PresenceSettings, _section(raw, "presence")),
        server=_typed(ServerSection, _section(raw, "server")),
        plugins=_typed(PluginsSection, _section(raw, "plugins")),
        monitor=_typed(MonitorSettings, _section(raw, "monitor") or _section(raw, "debug")),
    )
