"""一次性数据迁移：旧表 smoking_records → behavior_sessions。

在 lifespan 建表后调用；旧表不存在时直接跳过，重复执行幂等
（依 behavior_sessions 的 (behavior_type, device_id, start_time) 唯一约束去重）。
迁移后旧表保留不删，避免不可逆操作。
"""

from __future__ import annotations

from datetime import UTC, datetime

from loguru import logger
from sqlalchemy import MetaData, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.database.models import BehaviorSession

_LEGACY_TABLE = "smoking_records"


async def migrate_smoking_to_behavior(session: AsyncSession) -> int:
    """把旧抽烟记录复制为 behavior_type='smoking' 的行为会话；返回新增条数。"""
    conn = await session.connection()
    has_legacy = await conn.run_sync(lambda sync_conn: inspect(sync_conn).has_table(_LEGACY_TABLE))
    if not has_legacy:
        return 0

    # 反射旧表（含 DateTime 列类型，值自动解析为 datetime）
    metadata = MetaData()
    await conn.run_sync(lambda sync_conn: metadata.reflect(sync_conn, only=[_LEGACY_TABLE]))
    legacy = metadata.tables[_LEGACY_TABLE]

    migrated = 0
    for row in (await session.execute(select(legacy))).all():
        mapping = row._mapping
        exists = await session.scalar(
            select(BehaviorSession.id).where(
                BehaviorSession.behavior_type == "smoking",
                BehaviorSession.device_id == mapping["device_id"],
                BehaviorSession.start_time == mapping["start_time"],
            )
        )
        if exists is not None:
            continue
        session.add(
            BehaviorSession(
                behavior_type="smoking",
                device_id=mapping["device_id"],
                start_time=mapping["start_time"],
                end_time=mapping["end_time"],
                duration_seconds=float(mapping["duration_seconds"]),
                created_at=mapping["created_at"] or datetime.now(UTC),
            )
        )
        migrated += 1
    await session.commit()
    if migrated:
        logger.info("迁移完成：{} 条 smoking_records → behavior_sessions", migrated)
    return migrated
