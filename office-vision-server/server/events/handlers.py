"""事件处理器：上报事件 → 幂等入库 → 业务派生。

处理链（全部基于 Event，模块间不直接调用）：
1. EventLog 幂等写入（event_id 唯一）
2. SmokingEnded → 生成/更新 SmokingRecord（一根烟一条）
3. AgentHeartbeat 心跳刷新
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database.models import AgentHeartbeat, EventLog, SmokingRecord
from server.events.types import IncomingEvent, to_utc_naive


class EventHandler:
    """单事件处理器；由 API 层在会话内调用。"""

    async def process(self, session: AsyncSession, event: IncomingEvent) -> bool:
        """处理单个事件；重复事件返回 False。"""
        if not await self._insert_log(session, event):
            return False
        if event.event_type == "SmokingEnded":
            await self._upsert_smoking_record(session, event)
        await self._touch_heartbeat(session, event.device_id)
        return True

    async def _insert_log(self, session: AsyncSession, event: IncomingEvent) -> bool:
        existing = await session.scalar(
            select(EventLog.id).where(EventLog.event_id == event.event_id)
        )
        if existing is not None:
            logger.debug("重复事件已忽略: {}", event.event_id)
            return False
        session.add(
            EventLog(
                event_id=event.event_id,
                device_id=event.device_id,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                payload_json=json.dumps(event.payload, ensure_ascii=False),
                received_at=datetime.now(UTC),
            )
        )
        return True

    async def _upsert_smoking_record(self, session: AsyncSession, event: IncomingEvent) -> None:
        payload: dict[str, Any] = event.payload
        try:
            start = to_utc_naive(datetime.fromisoformat(str(payload["start_time"])))
            end = to_utc_naive(datetime.fromisoformat(str(payload["end_time"])))
            duration = float(payload["duration_seconds"])
        except (KeyError, ValueError):
            logger.warning("SmokingEnded payload 不完整: {}", event.event_id)
            return
        record = await session.scalar(
            select(SmokingRecord).where(
                SmokingRecord.device_id == event.device_id,
                SmokingRecord.start_time == start,
            )
        )
        if record is None:
            session.add(
                SmokingRecord(
                    device_id=event.device_id,
                    start_time=start,
                    end_time=end,
                    duration_seconds=duration,
                    created_at=datetime.now(UTC),
                )
            )

    async def _touch_heartbeat(self, session: AsyncSession, device_id: str) -> None:
        heartbeat = await session.get(AgentHeartbeat, device_id)
        if heartbeat is None:
            session.add(
                AgentHeartbeat(device_id=device_id, last_seen_at=datetime.now(UTC), event_count=1)
            )
        else:
            heartbeat.last_seen_at = datetime.now(UTC)
            heartbeat.event_count += 1
