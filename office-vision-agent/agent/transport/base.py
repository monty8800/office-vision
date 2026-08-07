"""事件上报通道抽象。

EventPublisher 接口：publish_batch(batch) -> bool
- HttpPublisher     HTTP API 上报 Server（当前）
- WebSocket / MQTT  后续扩展（新增子类即可，禁止修改 EventPusher）

禁止：Agent 直接操作 Server 数据库；Agent 直接控制 Home Assistant。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

#: 上报批次：事件 JSON 契约（event_id/device_id/event_type/occurred_at/payload）
EventBatch = list[dict[str, Any]]


class EventPublisher(ABC):
    """事件上报通道统一接口。"""

    name: str = "base"

    @abstractmethod
    async def publish_batch(self, batch: EventBatch) -> bool:
        """上报一批事件；成功返回 True，失败返回 False（触发离线缓存）。"""

    async def close(self) -> None:  # noqa: B027  默认无操作，子类按需覆写
        """释放资源。"""
