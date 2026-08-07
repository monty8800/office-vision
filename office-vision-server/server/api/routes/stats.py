"""Dashboard 统计接口（迁移自原型 backend，新增 device_id 维度）。

GET /api/smoking/today    今日次数/累计/平均
GET /api/smoking/records  记录分页
GET /api/smoking/trend    近 N 天趋势（补零）
GET /api/presence         在岗状态（由最近 Presence 事件推导）
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, field_serializer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database.models import EventLog, SmokingRecord
from server.events.types import iso_utc

router = APIRouter(prefix="/api", tags=["stats"])


def _local_day_start_utc(day: date) -> datetime:
    """本地某日 00:00 的 UTC 墙钟 naive 表示（与入库存储格式一致）。"""
    local_tz = datetime.now().astimezone().tzinfo
    return (
        datetime.combine(day, datetime.min.time(), tzinfo=local_tz)
        .astimezone(UTC)
        .replace(tzinfo=None)
    )


class TodaySummary(BaseModel):
    count: int
    total_seconds: float
    avg_seconds: float


class SmokingRecordItem(BaseModel):
    id: int
    device_id: str
    start_time: datetime
    end_time: datetime
    duration_seconds: float

    @field_serializer("start_time", "end_time")
    def _serialize_utc(self, v: datetime) -> str:
        return iso_utc(v)  # 库中为 UTC 墙钟，输出带时区标记供前端转本地


class RecordList(BaseModel):
    items: list[SmokingRecordItem]
    limit: int
    offset: int


class DailyStat(BaseModel):
    day: date
    count: int
    total_seconds: float


class Trend(BaseModel):
    days: list[DailyStat]


async def _get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """会话依赖：由 main.py 挂载的 app.state.db 提供。"""
    db = request.app.state.db
    async with db.session_scope() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(_get_db)]


@router.get("/smoking/today", response_model=TodaySummary, summary="今日抽烟统计")
async def today(session: SessionDep, device_id: str | None = None) -> TodaySummary:
    since = _local_day_start_utc(datetime.now().astimezone().date())  # 本地今日的零点
    stmt = select(
        func.count(SmokingRecord.id),
        func.coalesce(func.sum(SmokingRecord.duration_seconds), 0.0),
    ).where(SmokingRecord.start_time >= since)
    if device_id:
        stmt = stmt.where(SmokingRecord.device_id == device_id)
    row = (await session.execute(stmt)).one()
    count, total = int(row[0]), float(row[1])
    return TodaySummary(
        count=count, total_seconds=total, avg_seconds=total / count if count else 0.0
    )


@router.get("/smoking/records", response_model=RecordList, summary="抽烟记录分页")
async def records(
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    device_id: str | None = None,
) -> RecordList:
    stmt = (
        select(SmokingRecord).order_by(SmokingRecord.start_time.desc()).limit(limit).offset(offset)
    )
    if device_id:
        stmt = stmt.where(SmokingRecord.device_id == device_id)
    rows = (await session.execute(stmt)).scalars().all()
    return RecordList(
        items=[
            SmokingRecordItem(
                id=r.id,
                device_id=r.device_id,
                start_time=r.start_time,
                end_time=r.end_time,
                duration_seconds=r.duration_seconds,
            )
            for r in rows
        ],
        limit=limit,
        offset=offset,
    )


@router.get("/smoking/trend", response_model=Trend, summary="近 N 天趋势")
async def trend(
    session: SessionDep, days: int = Query(default=7, ge=1, le=90), device_id: str | None = None
) -> Trend:
    today_local = datetime.now().astimezone().date()
    since = _local_day_start_utc(today_local - timedelta(days=days - 1))
    # 存的是 UTC 墙钟，按本地时区分组才符合用户直觉
    day_expr = func.date(SmokingRecord.start_time, "localtime")
    stmt = (
        select(
            day_expr.label("day"),
            func.count(SmokingRecord.id),
            func.coalesce(func.sum(SmokingRecord.duration_seconds), 0.0),
        )
        .where(SmokingRecord.start_time >= since)
        .group_by(day_expr)
    )
    if device_id:
        stmt = stmt.where(SmokingRecord.device_id == device_id)
    rows = (await session.execute(stmt)).all()
    by_day: dict[str, tuple[int, float]] = {str(r.day): (int(r[1]), float(r[2])) for r in rows}
    stats: list[DailyStat] = []
    for i in range(days):
        day = today_local - timedelta(days=days - 1 - i)
        count, total = by_day.get(day.isoformat(), (0, 0.0))
        stats.append(DailyStat(day=day, count=count, total_seconds=total))
    return Trend(days=stats)


_PRESENCE_STATES = {
    "SeatOccupied": "working",
    "SeatEmpty": "away",
    "PresenceSleeping": "sleeping",
    "PresenceResumed": "working",
}


@router.get("/presence", summary="在岗状态（由最近 Presence 事件推导）")
async def presence(session: SessionDep) -> dict[str, Any]:
    stmt = (
        select(EventLog.device_id, EventLog.event_type, EventLog.occurred_at)
        .where(EventLog.event_type.in_(list(_PRESENCE_STATES)))
        .order_by(EventLog.occurred_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    latest: dict[str, dict[str, str]] = {}
    for device_id, event_type, occurred_at in rows:
        if device_id not in latest:
            latest[str(device_id)] = {
                "state": _PRESENCE_STATES[str(event_type)],
                "since": iso_utc(occurred_at),
            }
    return {"devices": latest}
