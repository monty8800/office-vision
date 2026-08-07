"""Server 端事件契约（与 Agent 的 JSON schema 严格一致）。

event_id / device_id / event_type / occurred_at / payload
Server 接收后分发：持久化、统计聚合、自动化触发。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


def to_utc_naive(value: datetime) -> datetime:
    """归一化为 UTC 墙钟 naive 时间（SQLite 不存时区，统一存储语义）。

    带时区的时间转换为 UTC；naive 时间视为本地时间转 UTC，
    避免两种语义混存导致排序/统计错乱。
    """
    if value.tzinfo is None:
        value = value.astimezone()  # naive 按本地时间解释
    return value.astimezone(UTC).replace(tzinfo=None)


def iso_utc(value: datetime) -> str:
    """库中 naive 值按 UTC 语义输出带时区标记的 ISO 串（前端转本地显示）。"""
    return value.replace(tzinfo=UTC).isoformat()


class IncomingEvent(BaseModel):
    """单个上报事件。"""

    event_id: str
    device_id: str
    event_type: str
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def _normalize_occurred_at(cls, v: datetime) -> datetime:
        return to_utc_naive(v)


class EventBatchRequest(BaseModel):
    """POST /api/events 请求体。"""

    events: list[IncomingEvent]


class EventBatchResponse(BaseModel):
    """上报结果。accepted 为实际入库条数（去重后）。"""

    accepted: int
    duplicates: int


class BehaviorEvent(BaseModel):
    """事件业务分发载体（持久化 / 统计 / 自动化共用）。"""

    event: IncomingEvent
