"""ORM 模型：事件流水 + 行为会话 + 客户端日志。

- EventLog         全部 Agent 事件的原始流水（event_id 唯一，天然幂等）
- BehaviorSession  行为会话记录（一次行为一条，抽烟/喝水/看手机等通用）
- AgentHeartbeat   Agent 在线状态（按 device_id upsert）
- ClientLog        客户端上传的日志 chunk（chunk_id 唯一，幂等）
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from server.database.base import Base


class EventLog(Base):
    """全部事件流水；event_id 幂等键防止网络重试重复入库。"""

    __tablename__ = "event_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BehaviorSession(Base):
    """行为会话记录（抽烟/喝水/看手机等通用；由 XxxEnded 事件生成）。"""

    __tablename__ = "behavior_sessions"
    __table_args__ = (
        UniqueConstraint(
            "behavior_type", "device_id", "start_time", name="uq_behavior_device_start"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    behavior_type: Mapped[str] = mapped_column(String(64), index=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentHeartbeat(Base):
    """Agent 心跳（最近一次上报时间），Dashboard 系统状态页使用。"""

    __tablename__ = "agent_heartbeats"

    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    event_count: Mapped[int] = mapped_column(default=0)


class ClientLog(Base):
    """客户端日志 chunk；chunk_id 幂等键防止网络重试重复入库。"""

    __tablename__ = "client_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    component: Mapped[str] = mapped_column(String(32), default="agent")
    trigger: Mapped[str] = mapped_column(String(16), default="periodic")
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    size: Mapped[int] = mapped_column(default=0)
    content: Mapped[str] = mapped_column(Text)
