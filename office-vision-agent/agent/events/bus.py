"""进程内异步事件总线。

- subscribe(event_type, handler) / publish(event)
- 支持按精确类型或基类订阅（订阅 Event 基类可接收全部事件）
- Vision Engine、插件、PresenceManager 只 publish，绝不互相直接调用
- Transport 模块订阅全部事件并上报 Server
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import TypeVar

from loguru import logger

from agent.events.types import Event

E = TypeVar("E", bound=Event)
Handler = Callable[[E], Awaitable[None]]
SyncHandler = Callable[[E], object]


class EventBus:
    """按事件类型订阅处理器；publish 时分发给匹配类型及其基类的处理器。

    同时支持异步处理器（await）与同步处理器（直接调用，
    用于视觉管线等运行在线程池中的同步上下文）。
    """

    def __init__(self) -> None:
        self._async_handlers: dict[type[Event], list[Handler[Event]]] = defaultdict(list)
        self._sync_handlers: dict[type[Event], list[SyncHandler[Event]]] = defaultdict(list)

    def subscribe(self, event_type: type[E], handler: Handler[E]) -> None:
        self._async_handlers[event_type].append(handler)  # type: ignore[arg-type]
        logger.debug("事件订阅(async): {}", event_type.__name__)

    def subscribe_sync(self, event_type: type[E], handler: SyncHandler[E]) -> None:
        self._sync_handlers[event_type].append(handler)  # type: ignore[arg-type]
        logger.debug("事件订阅(sync): {}", event_type.__name__)

    async def publish(self, event: Event) -> None:
        logger.debug("发布事件: {} (device={})", event.event_type, event.device_id)
        for event_type, sync_handlers in self._sync_handlers.items():
            if isinstance(event, event_type):
                for handler in sync_handlers:
                    try:
                        handler(event)
                    except Exception:
                        logger.exception("同步事件处理器执行失败: {}", handler)
        for event_type, async_handlers in self._async_handlers.items():
            if isinstance(event, event_type):
                for handler in async_handlers:
                    try:
                        await handler(event)
                    except Exception:
                        logger.exception("事件处理器执行失败: {}", handler)
