"""EventPusher：事件上报调度器。

机制（保证不丢、不乱序）：
1. 订阅 EventBus 全部事件 → 一律先写入 OfflineStore（本地 SQLite 队列）
2. 定时从队列头部取批 → HttpPublisher 上报
3. 上报成功才从队列移除；失败则留在队列，下个周期重试

Server 在线时队列近乎即时清空；离线时无限堆积直至恢复。
Agent 永不直接访问 Server 数据库（第一原则）。
"""

from __future__ import annotations

import asyncio

from loguru import logger

from agent.events.bus import EventBus
from agent.events.types import Event
from agent.transport.base import EventPublisher
from agent.transport.offline_store import OfflineStore


class EventPusher:
    """事件 → 本地队列 → 批量上报。"""

    def __init__(
        self,
        publisher: EventPublisher,
        store: OfflineStore,
        bus: EventBus,
        push_interval_seconds: float = 5.0,
        batch_size: int = 100,
    ) -> None:
        self._publisher = publisher
        self._store = store
        self._interval = max(push_interval_seconds, 0.5)
        self._batch_size = batch_size
        self._running = False
        bus.subscribe(Event, self._on_event)

    async def start(self) -> None:
        await self._store.open()

    async def _on_event(self, event: Event) -> None:
        await self._store.append([event.to_dict()])

    async def run(self) -> None:
        """推送主循环。"""
        self._running = True
        logger.info("事件推送器启动（间隔 {}s / 批 {}）", self._interval, self._batch_size)
        while self._running:
            try:
                await self.flush_once()
            except Exception:
                logger.exception("事件推送异常（下周期重试）")
            await asyncio.sleep(self._interval)

    async def flush_once(self) -> bool:
        """尝试推送一批；成功返回 True（队列为空也返回 True）。"""
        rows = await self._store.pending(self._batch_size)
        if not rows:
            return True
        events = [event for _, event in rows]
        if await self._publisher.publish_batch(events):
            await self._store.remove([row_id for row_id, _ in rows])
            return True
        return False

    async def stop(self) -> None:
        """停止前尽力冲刷一次，随后释放资源。"""
        self._running = False
        try:
            await self.flush_once()
        except Exception:
            logger.exception("停止前冲刷失败（事件保留在离线缓存）")
        await self._publisher.close()
        await self._store.close()
        logger.info("事件推送器已停止")
