"""Agent 事件接收与查询接口。

POST /api/events        批量接收事件（event_id 幂等）
GET  /api/events        最近事件流水（Dashboard Timeline）
GET  /api/agents        Agent 在线状态（心跳）
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.events.handlers import EventHandler
from server.events.types import EventBatchRequest, EventBatchResponse, iso_utc

router = APIRouter(prefix="/api", tags=["events"])
_handler = EventHandler()


async def _get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """会话依赖：由 main.py 挂载的 app.state.db 提供。"""
    db = request.app.state.db
    async with db.session_scope() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(_get_db)]


@router.post("/events", response_model=EventBatchResponse, summary="批量接收 Agent 事件")
async def receive_events(batch: EventBatchRequest, session: SessionDep) -> EventBatchResponse:
    accepted = 0
    for event in batch.events:
        if await _handler.process(session, event):
            accepted += 1
    await session.commit()
    return EventBatchResponse(accepted=accepted, duplicates=len(batch.events) - accepted)


@router.get("/events", summary="最近事件流水")
async def recent_events(
    session: SessionDep, limit: int = 50, device_id: str | None = None
) -> dict[str, Any]:
    from server.database.models import EventLog  # noqa: PLC0415

    stmt = select(EventLog).order_by(EventLog.occurred_at.desc()).limit(min(limit, 500))
    if device_id:
        stmt = stmt.where(EventLog.device_id == device_id)
    rows = (await session.execute(stmt)).scalars().all()
    return {
        "events": [
            {
                "event_id": r.event_id,
                "device_id": r.device_id,
                "event_type": r.event_type,
                "occurred_at": iso_utc(r.occurred_at),
            }
            for r in rows
        ]
    }


@router.get("/agents", summary="Agent 在线状态")
async def agents(session: SessionDep) -> dict[str, Any]:
    from server.database.models import AgentHeartbeat  # noqa: PLC0415

    rows = (await session.execute(select(AgentHeartbeat))).scalars().all()
    return {
        "agents": [
            {
                "device_id": r.device_id,
                "last_seen_at": iso_utc(r.last_seen_at),
                "event_count": r.event_count,
                "online": _is_online(r.last_seen_at),
            }
            for r in rows
        ]
    }


def _is_online(last_seen: datetime, threshold_seconds: float = 60.0) -> bool:
    if last_seen.tzinfo is None:  # SQLite 不保存时区，按 UTC 处理
        last_seen = last_seen.replace(tzinfo=UTC)
    return (datetime.now(UTC) - last_seen).total_seconds() <= threshold_seconds
