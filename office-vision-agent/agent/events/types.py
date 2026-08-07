"""领域事件类型定义。

事件是系统唯一的通信语言：Vision Engine、插件、PresenceManager 只发布事件，
Transport 订阅事件上报 Server，模块之间禁止直接调用。

事件契约（与 Server 的 JSON schema 对齐）：
    event_id / device_id / event_type / occurred_at / payload
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class Event:
    """所有领域事件的基类。"""

    device_id: str
    event_id: str = field(default_factory=_new_id)
    occurred_at: datetime = field(default_factory=_now)

    @property
    def event_type(self) -> str:
        return type(self).__name__

    def payload(self) -> dict[str, Any]:
        """子类覆写：携带各自的结构化数据。"""
        return {}

    def to_dict(self) -> dict[str, Any]:
        """HTTP 上报的 JSON 表示。"""
        return {
            "event_id": self.event_id,
            "device_id": self.device_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            "payload": self.payload(),
        }


# ---- Presence 相关事件 ----


@dataclass(frozen=True)
class PersonDetected(Event):
    """画面中检测到人（每帧判定，用于 Presence 输入）。"""


@dataclass(frozen=True)
class PersonLost(Event):
    """画面中人员消失。"""


@dataclass(frozen=True)
class SeatOccupied(Event):
    """确认在岗（人稳定出现）。"""


@dataclass(frozen=True)
class SeatEmpty(Event):
    """确认离岗（离开超过缓冲时间）。"""


@dataclass(frozen=True)
class PresenceSleeping(Event):
    """系统进入休眠：重量级组件已停止，仅保留轻量检测。"""


@dataclass(frozen=True)
class PresenceResumed(Event):
    """人回来，系统从休眠恢复。"""


# ---- 系统事件 ----


@dataclass(frozen=True)
class AgentAlive(Event):
    """周期性心跳：证明 Agent 进程存活（与业务事件无关，避免安静期被误判离线）。"""


# ---- 行为事件 ----


@dataclass(frozen=True)
class SmokingStarted(Event):
    """一次抽烟行为开始。"""


@dataclass(frozen=True)
class SmokingEnded(Event):
    """一次抽烟行为结束，携带完整会话信息。"""

    start_time: datetime = field(default_factory=_now)
    end_time: datetime = field(default_factory=_now)
    duration_seconds: float = 0.0

    def payload(self) -> dict[str, Any]:
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_seconds": self.duration_seconds,
        }


# ---- 序列化注册表（Transport / Server 共用） ----

EVENT_REGISTRY: dict[str, type[Event]] = {
    cls.__name__: cls
    for cls in (
        PersonDetected,
        PersonLost,
        SeatOccupied,
        SeatEmpty,
        PresenceSleeping,
        PresenceResumed,
        AgentAlive,
        SmokingStarted,
        SmokingEnded,
    )
}


def event_from_dict(data: dict[str, Any]) -> Event:
    """从 JSON dict 还原事件（Server 接收端 / Agent 离线缓存重放）。"""
    event_type = str(data.get("event_type", ""))
    cls = EVENT_REGISTRY.get(event_type)
    if cls is None:
        msg = f"未知事件类型: {event_type}"
        raise ValueError(msg)
    common: dict[str, Any] = {
        "device_id": str(data.get("device_id", "")),
        "event_id": str(data.get("event_id", _new_id())),
        "occurred_at": datetime.fromisoformat(str(data.get("occurred_at"))),
    }
    payload = data.get("payload") or {}
    if cls is SmokingEnded:
        return SmokingEnded(
            **common,
            start_time=datetime.fromisoformat(str(payload["start_time"])),
            end_time=datetime.fromisoformat(str(payload["end_time"])),
            duration_seconds=float(payload["duration_seconds"]),
        )
    return cls(**common)
