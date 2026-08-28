"""客户端日志接收与查询接口。

POST /api/logs           接收单个日志 chunk（chunk_id 幂等）
GET  /api/logs           chunk 元数据列表（Dashboard 客户端日志页）
GET  /api/logs/{chunk_id} 单个 chunk 完整内容
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, field_validator
from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database.models import ClientLog
from server.events.types import iso_utc, to_utc_naive

router = APIRouter(prefix="/api", tags=["logs"])

_MAX_CONTENT_BYTES = 1024 * 1024  # 单 chunk 上限 1MB（Agent 侧按 256KB 切分）
_CLEANUP_THROTTLE_SECONDS = 3600  # retention 清理节流：最多每小时一次


class ClientLogUpload(BaseModel):
    """POST /api/logs 请求体（单个 chunk）。"""

    chunk_id: str
    device_id: str
    component: str = "agent"
    trigger: str = "periodic"
    logged_at: datetime
    content: str

    @field_validator("logged_at")
    @classmethod
    def _normalize_logged_at(cls, v: datetime) -> datetime:
        return to_utc_naive(v)


class ClientLogResponse(BaseModel):
    """上报结果。accepted=1 为入库，duplicates=1 为 chunk_id 重复。"""

    accepted: int
    duplicates: int


async def _get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """会话依赖：由 main.py 挂载的 app.state.db 提供。"""
    db = request.app.state.db
    async with db.session_scope() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(_get_db)]


@router.post("/logs", response_model=ClientLogResponse, summary="接收客户端日志 chunk")
async def receive_log(
    chunk: ClientLogUpload, request: Request, session: SessionDep
) -> ClientLogResponse:
    if len(chunk.content.encode("utf-8")) > _MAX_CONTENT_BYTES:
        raise HTTPException(status_code=413, detail="日志 chunk 超过 1MB 上限")
    existing = await session.scalar(
        select(ClientLog.id).where(ClientLog.chunk_id == chunk.chunk_id)
    )
    if existing is not None:
        return ClientLogResponse(accepted=0, duplicates=1)
    session.add(
        ClientLog(
            chunk_id=chunk.chunk_id,
            device_id=chunk.device_id,
            component=chunk.component,
            trigger=chunk.trigger,
            logged_at=chunk.logged_at,
            received_at=datetime.now(UTC),
            size=len(chunk.content.encode("utf-8")),
            content=chunk.content,
        )
    )
    await session.commit()
    await _cleanup_expired(request, session)
    return ClientLogResponse(accepted=1, duplicates=0)


@router.get("/logs", summary="客户端日志 chunk 列表（不含内容）")
async def list_logs(
    session: SessionDep, device_id: str | None = None, limit: int = 50, offset: int = 0
) -> dict[str, Any]:
    stmt = select(ClientLog).order_by(ClientLog.logged_at.desc())
    count_stmt = select(func.count()).select_from(ClientLog)
    if device_id:
        stmt = stmt.where(ClientLog.device_id == device_id)
        count_stmt = count_stmt.where(ClientLog.device_id == device_id)
    total = await session.scalar(count_stmt)
    rows = (
        (await session.execute(stmt.limit(min(limit, 200)).offset(max(offset, 0)))).scalars().all()
    )
    return {
        "total": total or 0,
        "chunks": [
            {
                "chunk_id": r.chunk_id,
                "device_id": r.device_id,
                "component": r.component,
                "trigger": r.trigger,
                "logged_at": iso_utc(r.logged_at),
                "received_at": iso_utc(r.received_at),
                "size": r.size,
            }
            for r in rows
        ],
    }


@router.get("/logs/{chunk_id}", summary="单个日志 chunk 完整内容")
async def log_detail(chunk_id: str, session: SessionDep) -> dict[str, Any]:
    row = await session.scalar(select(ClientLog).where(ClientLog.chunk_id == chunk_id))
    if row is None:
        raise HTTPException(status_code=404, detail="日志 chunk 不存在")
    return {
        "chunk_id": row.chunk_id,
        "device_id": row.device_id,
        "component": row.component,
        "trigger": row.trigger,
        "logged_at": iso_utc(row.logged_at),
        "received_at": iso_utc(row.received_at),
        "size": row.size,
        "content": row.content,
    }


async def _cleanup_expired(request: Request, session: AsyncSession) -> None:
    """删除超过保留期的日志；app.state 节流，避免每次 POST 都扫表。"""
    config = getattr(request.app.state, "config", None)
    retention_days = getattr(getattr(config, "logs", None), "retention_days", 14)
    now = time.monotonic()
    last = getattr(request.app.state, "logs_last_cleanup", 0.0)
    if now - last < _CLEANUP_THROTTLE_SECONDS:
        return
    request.app.state.logs_last_cleanup = now
    # 与插入时同为 UTC aware，SQLite/PG 两种方言下比较语义一致
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = cast(
        "CursorResult[Any]",
        await session.execute(delete(ClientLog).where(ClientLog.received_at < cutoff)),
    )
    await session.commit()
    if result.rowcount:
        logger.info("客户端日志清理：删除 {} 条超过 {} 天的记录", result.rowcount, retention_days)
