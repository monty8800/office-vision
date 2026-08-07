"""离线事件缓存：Server 不可用时事件写入本地 SQLite。

网络恢复后按时间顺序自动批量同步，保证不丢失数据。
注意：此 SQLite 仅作传输缓冲队列，Agent 不存储业务数据（第一原则）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


class OfflineStore:
    """FIFO 事件缓冲队列（aiosqlite）。"""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        await self._db.execute(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def append(self, events: list[dict[str, Any]]) -> None:
        """将失败批次写入队列（保持时间顺序）。"""
        assert self._db is not None
        rows = [
            (str(event.get("occurred_at", "")), json.dumps(event, ensure_ascii=False))
            for event in events
        ]
        await self._db.executemany(
            "INSERT INTO pending_events (occurred_at, payload) VALUES (?, ?)", rows
        )
        await self._db.commit()

    async def pending(self, limit: int = 100) -> list[tuple[int, dict[str, Any]]]:
        """取出最早的一批（id, 事件 dict）。"""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT id, payload FROM pending_events ORDER BY id LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [(int(row[0]), json.loads(str(row[1]))) for row in rows]

    async def remove(self, ids: list[int]) -> None:
        """上报成功后移除。"""
        if not ids:
            return
        assert self._db is not None
        placeholders = ",".join("?" for _ in ids)
        await self._db.execute(f"DELETE FROM pending_events WHERE id IN ({placeholders})", ids)
        await self._db.commit()

    async def count(self) -> int:
        assert self._db is not None
        cursor = await self._db.execute("SELECT COUNT(*) FROM pending_events")
        row = await cursor.fetchone()
        return int(row[0]) if row else 0
