"""坐席(在岗/离开)分析接口：由 EventLog 的 Presence 事件推导坐席会话与每日在岗时长。

数据来源（无需新表，全部取自已在库的 Presence 事件）：
- SeatOccupied / PresenceResumed   → 进入/在岗（occupant=True）
- SeatEmpty   / PresenceSleeping   → 离开/离岗（occupant=False）

接口：
- GET /api/sitting/today       今日：总时长/坐席次数/离开次数/平均/当前是否在座
- GET /api/sitting/daily       近 N 天每日：总时长/次数/离开次数（补零）
- GET /api/sitting/sessions    坐席会话明细分页（进入→离开+时长；进行中 end_time 为空）

merge_gap_seconds（默认 60）：离开时长小于该值视为同一次连续在岗。
人检测单帧丢失会立刻触发 SeatEmpty，造成毫秒级碎片；合并后才是"真实的离开次数"。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, field_serializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database.models import EventLog
from server.events.types import iso_utc

router = APIRouter(prefix="/api", tags=["sitting"])

# 在岗/离岗事件 → occupant 布尔
_OCCUPANT_TRUE = {"SeatOccupied", "PresenceResumed"}
_OCCUPANT_FALSE = {"SeatEmpty", "PresenceSleeping"}
_OCCUPANCY_EVENTS = _OCCUPANT_TRUE | _OCCUPANT_FALSE

_DEFAULT_MERGE_GAP = 60.0  # 秒


def _local_day_start_utc(day: date) -> datetime:
    """本地某日 00:00 的 UTC 墙钟 naive 表示（与入库存储格式一致）。"""
    local_tz = datetime.now().astimezone().tzinfo
    return (
        datetime.combine(day, datetime.min.time(), tzinfo=local_tz)
        .astimezone(UTC)
        .replace(tzinfo=None)
    )


async def _get_db(request: Request) -> AsyncIterator[AsyncSession]:
    db = request.app.state.db
    async with db.session_scope() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(_get_db)]


class SessionItem(BaseModel):
    start_time: datetime
    end_time: datetime | None = None  # None = 仍在座（进行中）
    duration_seconds: float

    @field_serializer("start_time", "end_time")
    def _serialize_utc(self, v: datetime | None) -> str | None:
        return iso_utc(v) if v is not None else None


class SittingToday(BaseModel):
    day: date
    total_seconds: float
    sessions: int
    leaves: int
    avg_seconds: float
    now_sitting: bool
    current_session_start: str | None = None
    first_sit_time: str | None = None
    last_leave_time: str | None = None
    last_leave_duration: float | None = None


class SittingDay(BaseModel):
    day: date
    total_seconds: float
    sessions: int
    leaves: int
    avg_seconds: float


class SittingDaily(BaseModel):
    days: list[SittingDay]


class SittingSessionList(BaseModel):
    items: list[SessionItem]
    limit: int
    offset: int


# ---- 核心：occupant 时间线 → 合并坐席会话 ----

_OCCUPANCY_QUERY_LIMIT = 5000  # 最多取最近 N 条 occupant 事件，防驻留振荡刷爆库导致查询慢


async def _fetch_occupancy(
    session: AsyncSession, device_id: str | None, until: datetime | None = None
) -> list[tuple[datetime, bool]]:
    """按时间升序返回最近 N 条 (occurred_at, occupant) 事件（用于构建 occupant 时间线）。

    只取最近 _OCCUPANCY_QUERY_LIMIT 条：即便驻留状态机异常刷出海量 Presence 事件，
    坐席分析也能限定在最近时间窗内，避免读几十万条拖慢接口。
    """
    stmt = select(EventLog.occurred_at, EventLog.event_type).where(
        EventLog.event_type.in_(_OCCUPANCY_EVENTS)
    )
    if until is not None:
        stmt = stmt.where(EventLog.occurred_at <= until)
    if device_id:
        stmt = stmt.where(EventLog.device_id == device_id)
    # 按时间倒序取最近 N 条，再反转回升序
    stmt = stmt.order_by(EventLog.occurred_at.desc()).limit(_OCCUPANCY_QUERY_LIMIT)
    rows = (await session.execute(stmt)).all()
    events = [(r[0], r[1] in _OCCUPANT_TRUE) for r in rows]
    events.reverse()
    return events


def _build_merged(
    events: list[tuple[datetime, bool]], merge_gap: float
) -> tuple[list[list[datetime | None]], bool]:
    """occupant 时间线 → 合并后的坐席会话（end None 表示仍在座）+ 最终 occupant。

    相邻两段坐席之间的缺勤 < merge_gap 时合并（视为同一次连续在岗）。
    """
    raw: list[list[datetime | None]] = []
    occupant = False
    seg_start: datetime | None = None
    for t, occ in events:
        if occ and not occupant:
            occupant = True
            seg_start = t
        elif not occ and occupant:
            occupant = False
            if seg_start is not None:
                raw.append([seg_start, t])
                seg_start = None
    final_occupant = occupant
    if occupant and seg_start is not None:
        raw.append([seg_start, None])  # 仍在座，未离席

    merged: list[list[datetime | None]] = []
    for seg in raw:
        if not merged:
            merged.append(list(seg))
            continue
        prev = merged[-1]
        # 两段均已结束，且间隙 < merge_gap → 合并终点
        if (
            prev[1] is not None
            and seg[0] is not None
            and (seg[0] - prev[1]).total_seconds() < merge_gap
        ):
            prev[1] = seg[1]
        else:
            merged.append(list(seg))
    return merged, final_occupant


def _clamp_day(
    segments: list[list[datetime | None]], day_start: datetime, day_end: datetime
) -> list[tuple[datetime, datetime]]:
    """把合并会话裁剪到 [day_start, day_end]，返回在当日内的 (start, end) 片段。"""
    out: list[tuple[datetime, datetime]] = []
    for s, e in segments:
        cs = s if s is not None else day_start
        ce = e if e is not None else day_end
        cs = max(cs, day_start)
        ce = min(ce, day_end)
        if ce > cs:
            out.append((cs, ce))
    return out


def _day_agg(
    segments: list[list[datetime | None]], day_start: datetime, day_end: datetime
) -> tuple[float, int, int, list[tuple[datetime, datetime]]]:
    """返回 (total_seconds, sessions, leaves, day_segments)。

    leaves = 在当日已结束的会话数（跨日未收尾/进行中不算"离开"）。
    """
    clamped = _clamp_day(segments, day_start, day_end)
    total = sum((ce - cs).total_seconds() for cs, ce in clamped)
    sessions = len(clamped)
    leaves = sum(1 for cs, ce in clamped if ce < day_end)
    return total, sessions, leaves, clamped


async def _segments_until(
    session: AsyncSession, device_id: str | None, until: datetime, merge_gap: float
) -> tuple[list[list[datetime | None]], bool]:
    events = await _fetch_occupancy(session, device_id, until)
    return _build_merged(events, merge_gap)


# ---- 接口 ----

@router.get("/sitting/today", response_model=SittingToday, summary="今日坐席/工作时长")
async def sitting_today(
    session: SessionDep,
    device_id: str | None = None,
    merge_gap_seconds: float = Query(default=_DEFAULT_MERGE_GAP, ge=0, le=3600),
) -> SittingToday:
    now_local = datetime.now().astimezone()
    day = now_local.date()
    day_start = _local_day_start_utc(day)
    now_utc = datetime.now(UTC).replace(tzinfo=None)
    segments, final_occupant = await _segments_until(
        session, device_id, now_utc, merge_gap_seconds
    )
    total, sessions, leaves, clamped = _day_agg(segments, day_start, now_utc)

    # 当前在座 = 最终 occupant 且当日仍有片段时间
    now_sitting = bool(final_occupant and total > 0)
    current_session_start = None
    first_sit_time = None
    last_leave_time = None
    last_leave_duration = None
    if clamped:
        first_sit_time = iso_utc(clamped[0][0])
        if now_sitting:
            current_session_start = iso_utc(clamped[-1][0])
        # 最近一次"已结束"的会话（离开时刻与时长）
        ended = [(cs, ce) for cs, ce in clamped if ce < now_utc]
        if ended:
            last_leave_time = iso_utc(ended[-1][1])
            last_leave_duration = max(0.0, (ended[-1][1] - ended[-1][0]).total_seconds())

    return SittingToday(
        day=day,
        total_seconds=total,
        sessions=sessions,
        leaves=leaves,
        avg_seconds=total / sessions if sessions else 0.0,
        now_sitting=now_sitting,
        current_session_start=current_session_start,
        first_sit_time=first_sit_time,
        last_leave_time=last_leave_time,
        last_leave_duration=last_leave_duration,
    )


@router.get("/sitting/daily", response_model=SittingDaily, summary="近 N 天每日坐席时长")
async def sitting_daily(
    session: SessionDep,
    days: int = Query(default=7, ge=1, le=90),
    device_id: str | None = None,
    merge_gap_seconds: float = Query(default=_DEFAULT_MERGE_GAP, ge=0, le=3600),
) -> SittingDaily:
    today = datetime.now().astimezone().date()
    now_utc = datetime.now(UTC).replace(tzinfo=None)
    segments, _ = await _segments_until(session, device_id, now_utc, merge_gap_seconds)

    result: list[SittingDay] = []
    for i in range(days):
        day = today - timedelta(days=days - 1 - i)
        day_start = _local_day_start_utc(day)
        day_end = (
            now_utc if day == today else _local_day_start_utc(day + timedelta(days=1))
        )
        total, sessions, leaves, _ = _day_agg(segments, day_start, day_end)
        result.append(
            SittingDay(
                day=day,
                total_seconds=total,
                sessions=sessions,
                leaves=leaves,
                avg_seconds=total / sessions if sessions else 0.0,
            )
        )
    return SittingDaily(days=result)


@router.get("/sitting/sessions", response_model=SittingSessionList, summary="坐席会话明细分页")
async def sitting_sessions(
    session: SessionDep,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    device_id: str | None = None,
    merge_gap_seconds: float = Query(default=_DEFAULT_MERGE_GAP, ge=0, le=3600),
) -> SittingSessionList:
    now_utc = datetime.now(UTC).replace(tzinfo=None)
    segments, _ = await _segments_until(session, device_id, now_utc, merge_gap_seconds)

    items: list[SessionItem] = []
    for s, e in segments:
        if s is None:
            continue
        # 只展示近 90 天，避免无限历史堆叠
        if s < now_utc - timedelta(days=90):
            continue
        end = e if e is not None else now_utc
        duration = max(0.0, (end - s).total_seconds())
        items.append(
            SessionItem(
                start_time=s,
                end_time=e,  # None 表示进行中
                duration_seconds=duration,
            )
        )
    items.sort(key=lambda x: x.start_time, reverse=True)
    return SittingSessionList(
        items=items[offset : offset + limit], limit=limit, offset=offset
    )


class SittingRangeDay(BaseModel):
    day: date
    total_seconds: float
    sessions: int
    leaves: int


class SittingRange(BaseModel):
    start: date
    end: date
    days: list[SittingRangeDay]
    total_seconds: float
    sessions: int
    leaves: int
    day_count: int  # 区间内自然日数
    active_days: int  # 有坐席数据的天数
    avg_per_day: float  # 日均坐席时长 = total / day_count


@router.get("/sitting/range", response_model=SittingRange, summary="指定日期区间坐席聚合")
async def sitting_range(
    session: SessionDep,
    start: date,
    end: date,
    device_id: str | None = None,
    merge_gap_seconds: float = Query(default=_DEFAULT_MERGE_GAP, ge=0, le=3600),
) -> SittingRange:
    """返回 [start, end]（含）的每日坐席数据 + 区间聚合（仅到今日为止）。"""
    today = datetime.now().astimezone().date()
    if start > end:
        start, end = end, start
    end = min(end, today)
    now_utc = datetime.now(UTC).replace(tzinfo=None)
    segments, _ = await _segments_until(session, device_id, now_utc, merge_gap_seconds)

    day_list: list[SittingRangeDay] = []
    d = start
    while d <= end:
        day_start = _local_day_start_utc(d)
        day_end = now_utc if d == today else _local_day_start_utc(d + timedelta(days=1))
        total, sessions, leaves, _ = _day_agg(segments, day_start, day_end)
        day_list.append(
            SittingRangeDay(day=d, total_seconds=total, sessions=sessions, leaves=leaves)
        )
        d += timedelta(days=1)

    # 区间整体聚合（避免跨午夜会话被跨日重复计）
    range_start_utc = _local_day_start_utc(start)
    range_end_utc = now_utc if end == today else _local_day_start_utc(end + timedelta(days=1))
    total, sessions, leaves, _ = _day_agg(segments, range_start_utc, range_end_utc)
    day_count = (end - start).days + 1
    return SittingRange(
        start=start,
        end=end,
        days=day_list,
        total_seconds=total,
        sessions=sessions,
        leaves=leaves,
        day_count=day_count,
        active_days=sum(1 for x in day_list if x.total_seconds > 0),
        avg_per_day=total / day_count if day_count else 0.0,
    )
