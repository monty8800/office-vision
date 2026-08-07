"""Dashboard 统计接口（行为泛化：/api/smoking/* → /api/behaviors/{behavior}/*）。

GET /api/behaviors                       已知行为清单（key + 中文名）
GET /api/behaviors/{behavior}/today      今日次数/累计/平均 + 最近一次
GET /api/behaviors/{behavior}/sessions   会话记录分页
GET /api/behaviors/{behavior}/trend      近 N 天趋势（补零，含周末）
GET /api/behaviors/{behavior}/hourly     某日 0-23 时分布（不限工作时间）
GET /api/presence                        在岗状态（由最近 Presence 事件推导）
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_serializer
from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database.models import BehaviorSession, EventLog
from server.events.types import BEHAVIOR_LABELS, iso_utc

router = APIRouter(prefix="/api", tags=["stats"])


def _local_day_start_utc(day: date) -> datetime:
    """本地某日 00:00 的 UTC 墙钟 naive 表示（与入库存储格式一致）。"""
    local_tz = datetime.now().astimezone().tzinfo
    return (
        datetime.combine(day, datetime.min.time(), tzinfo=local_tz)
        .astimezone(UTC)
        .replace(tzinfo=None)
    )


def _require_behavior(behavior: str) -> str:
    """行为类型白名单校验；未知行为返回 404。"""
    if behavior not in BEHAVIOR_LABELS:
        raise HTTPException(status_code=404, detail=f"未知行为类型: {behavior}")
    return behavior


class BehaviorInfo(BaseModel):
    key: str
    label: str


class TodaySummary(BaseModel):
    count: int
    total_seconds: float
    avg_seconds: float
    last_start_time: str | None = None  # 最近一次（不限今日），前端算"距上次"
    last_duration_seconds: float | None = None


class SessionItem(BaseModel):
    id: int
    device_id: str
    start_time: datetime
    end_time: datetime
    duration_seconds: float

    @field_serializer("start_time", "end_time")
    def _serialize_utc(self, v: datetime) -> str:
        return iso_utc(v)  # 库中为 UTC 墙钟，输出带时区标记供前端转本地


class SessionList(BaseModel):
    items: list[SessionItem]
    limit: int
    offset: int


class DailyStat(BaseModel):
    day: date
    count: int
    total_seconds: float


class Trend(BaseModel):
    days: list[DailyStat]


class HourBucket(BaseModel):
    hour: int
    count: int
    total_seconds: float


class Hourly(BaseModel):
    date: date
    hours: list[HourBucket]


async def _get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """会话依赖：由 main.py 挂载的 app.state.db 提供。"""
    db = request.app.state.db
    async with db.session_scope() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(_get_db)]


@router.get("/behaviors", summary="已知行为清单")
async def behaviors() -> dict[str, list[BehaviorInfo]]:
    return {
        "behaviors": [
            BehaviorInfo(key=key, label=label) for key, label in BEHAVIOR_LABELS.items()
        ]
    }


@router.get(
    "/behaviors/{behavior}/today", response_model=TodaySummary, summary="今日行为统计"
)
async def today(
    behavior: str, session: SessionDep, device_id: str | None = None
) -> TodaySummary:
    behavior = _require_behavior(behavior)
    since = _local_day_start_utc(datetime.now().astimezone().date())  # 本地今日的零点
    stmt = select(
        func.count(BehaviorSession.id),
        func.coalesce(func.sum(BehaviorSession.duration_seconds), 0.0),
    ).where(BehaviorSession.behavior_type == behavior, BehaviorSession.start_time >= since)
    if device_id:
        stmt = stmt.where(BehaviorSession.device_id == device_id)
    row = (await session.execute(stmt)).one()
    count, total = int(row[0]), float(row[1])

    # 最近一次会话（不限今日）：概览页"距上次 xx 分钟"用
    last_stmt = (
        select(BehaviorSession)
        .where(BehaviorSession.behavior_type == behavior)
        .order_by(BehaviorSession.start_time.desc())
        .limit(1)
    )
    if device_id:
        last_stmt = last_stmt.where(BehaviorSession.device_id == device_id)
    last = (await session.execute(last_stmt)).scalar_one_or_none()

    return TodaySummary(
        count=count,
        total_seconds=total,
        avg_seconds=total / count if count else 0.0,
        last_start_time=iso_utc(last.start_time) if last else None,
        last_duration_seconds=last.duration_seconds if last else None,
    )


@router.get(
    "/behaviors/{behavior}/sessions", response_model=SessionList, summary="行为会话分页"
)
async def sessions(
    behavior: str,
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    device_id: str | None = None,
) -> SessionList:
    behavior = _require_behavior(behavior)
    stmt = (
        select(BehaviorSession)
        .where(BehaviorSession.behavior_type == behavior)
        .order_by(BehaviorSession.start_time.desc())
        .limit(limit)
        .offset(offset)
    )
    if device_id:
        stmt = stmt.where(BehaviorSession.device_id == device_id)
    rows = (await session.execute(stmt)).scalars().all()
    return SessionList(
        items=[
            SessionItem(
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


@router.get("/behaviors/{behavior}/trend", response_model=Trend, summary="近 N 天趋势")
async def trend(
    behavior: str,
    session: SessionDep,
    days: int = Query(default=7, ge=1, le=90),
    device_id: str | None = None,
) -> Trend:
    behavior = _require_behavior(behavior)
    today_local = datetime.now().astimezone().date()
    since = _local_day_start_utc(today_local - timedelta(days=days - 1))
    # 存的是 UTC 墙钟，按本地时区分组才符合用户直觉（含周末的全部自然日）
    day_expr = func.date(BehaviorSession.start_time, "localtime")
    stmt = (
        select(
            day_expr.label("day"),
            func.count(BehaviorSession.id),
            func.coalesce(func.sum(BehaviorSession.duration_seconds), 0.0),
        )
        .where(BehaviorSession.behavior_type == behavior, BehaviorSession.start_time >= since)
        .group_by(day_expr)
    )
    if device_id:
        stmt = stmt.where(BehaviorSession.device_id == device_id)
    rows = (await session.execute(stmt)).all()
    by_day: dict[str, tuple[int, float]] = {str(r.day): (int(r[1]), float(r[2])) for r in rows}
    stats: list[DailyStat] = []
    for i in range(days):
        day = today_local - timedelta(days=days - 1 - i)
        count, total = by_day.get(day.isoformat(), (0, 0.0))
        stats.append(DailyStat(day=day, count=count, total_seconds=total))
    return Trend(days=stats)


@router.get(
    "/behaviors/{behavior}/hourly", response_model=Hourly, summary="某日 0-23 时分布"
)
async def hourly(
    behavior: str,
    session: SessionDep,
    date_param: Annotated[str, Query(alias="date")] = "today",
    device_id: str | None = None,
) -> Hourly:
    behavior = _require_behavior(behavior)
    try:
        day = (
            datetime.now().astimezone().date()
            if date_param == "today"
            else date.fromisoformat(date_param)
        )
    except ValueError:
        raise HTTPException(status_code=422, detail=f"date 参数无效: {date_param}") from None
    start_utc = _local_day_start_utc(day)
    end_utc = _local_day_start_utc(day + timedelta(days=1))
    # 按本地小时分组；全天 0-23 时，加班/夜间/周末行为同样计入
    hour_expr = func.cast(func.strftime("%H", BehaviorSession.start_time, "localtime"), Integer)
    stmt = (
        select(
            hour_expr.label("hour"),
            func.count(BehaviorSession.id),
            func.coalesce(func.sum(BehaviorSession.duration_seconds), 0.0),
        )
        .where(
            BehaviorSession.behavior_type == behavior,
            BehaviorSession.start_time >= start_utc,
            BehaviorSession.start_time < end_utc,
        )
        .group_by(hour_expr)
    )
    if device_id:
        stmt = stmt.where(BehaviorSession.device_id == device_id)
    rows = (await session.execute(stmt)).all()
    by_hour: dict[int, tuple[int, float]] = {
        int(r.hour): (int(r[1]), float(r[2])) for r in rows
    }
    hours = [
        HourBucket(hour=h, count=count, total_seconds=total)
        for h in range(24)
        for count, total in [by_hour.get(h, (0, 0.0))]
    ]
    return Hourly(date=day, hours=hours)


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
