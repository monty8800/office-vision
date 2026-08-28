"""Server 配置系统。

- YAML 为唯一配置源（config/server.yaml），禁止硬编码（第四原则）
- 环境变量 OVA_SERVER_CONFIG 覆盖配置路径；OVA_DATABASE_URL 覆盖数据库 URL
- 敏感信息（HA token）建议走环境变量，不入库配置文件
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "server.yaml"


@dataclass(frozen=True)
class ServerSection:
    name: str = "office-vision-server"
    host: str = "0.0.0.0"  # noqa: S104
    port: int = 8000
    log_level: str = "INFO"


@dataclass(frozen=True)
class DatabaseSection:
    url: str = "sqlite+aiosqlite:///data/office_vision.db"


@dataclass(frozen=True)
class EventsSection:
    dedup_window_seconds: int = 5


@dataclass(frozen=True)
class LogsSection:
    retention_days: int = 14


@dataclass(frozen=True)
class HomeAssistantSection:
    url: str = "http://localhost:8123"
    token: str = ""


@dataclass(frozen=True)
class AutomationSection:
    enabled: bool = False
    home_assistant: HomeAssistantSection = field(default_factory=HomeAssistantSection)


@dataclass(frozen=True)
class UsersSection:
    default_user: str = "admin"


def _normalize_database_url(url: str) -> str:
    """裸 postgres(ql):// 连接串补 asyncpg 驱动（PaaS 注入的 URL 通常不带驱动名）。"""
    if url.startswith(("postgres://", "postgresql://")) and "+" not in url.split("://", 1)[0]:
        return url.replace("postgres://", "postgresql+asyncpg://", 1).replace(
            "postgresql://", "postgresql+asyncpg://", 1
        )
    return url


@dataclass(frozen=True)
class ServerConfig:
    """全部配置的聚合视图。"""

    server: ServerSection = field(default_factory=ServerSection)
    database: DatabaseSection = field(default_factory=DatabaseSection)
    events: EventsSection = field(default_factory=EventsSection)
    logs: LogsSection = field(default_factory=LogsSection)
    automation: AutomationSection = field(default_factory=AutomationSection)
    users: UsersSection = field(default_factory=UsersSection)

    @property
    def database_url(self) -> str:
        # 环境变量优先（容器化部署覆盖）
        url = os.environ.get("OVA_DATABASE_URL") or self.database.url
        return _normalize_database_url(url)


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key) or {}
    if not isinstance(value, dict):
        msg = f"配置段 {key} 必须是映射"
        raise ValueError(msg)
    return value


def _typed(cls: type[Any], data: dict[str, Any]) -> Any:
    known = {f for f in cls.__dataclass_fields__}  # noqa: C416
    return cls(**{k: v for k, v in data.items() if k in known})


def load_config(path: str | Path | None = None) -> ServerConfig:
    """加载并校验配置文件。"""
    config_path = Path(path or os.environ.get("OVA_SERVER_CONFIG") or DEFAULT_CONFIG_PATH)
    if not config_path.exists():
        msg = f"配置文件不存在: {config_path}（可用 OVA_SERVER_CONFIG 指定）"
        raise FileNotFoundError(msg)
    with config_path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        msg = f"配置文件格式错误: {config_path}"
        raise ValueError(msg)
    automation_raw = _section(raw, "automation")
    return ServerConfig(
        server=_typed(ServerSection, _section(raw, "server")),
        database=_typed(DatabaseSection, _section(raw, "database")),
        events=_typed(EventsSection, _section(raw, "events")),
        logs=_typed(LogsSection, _section(raw, "logs")),
        automation=AutomationSection(
            enabled=bool(automation_raw.get("enabled", False)),
            home_assistant=_typed(
                HomeAssistantSection,
                _section(automation_raw, "home_assistant"),
            ),
        ),
        users=_typed(UsersSection, _section(raw, "users")),
    )
