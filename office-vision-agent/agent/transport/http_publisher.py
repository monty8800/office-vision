"""HTTP 上报通道：POST {server_url}/api/events。"""

from __future__ import annotations

import httpx
from loguru import logger

from agent.transport.base import EventBatch, EventPublisher


class HttpPublisher(EventPublisher):
    """批量 JSON 上报；网络错误/非 2xx 一律返回 False 触发离线缓存。"""

    name = "http"

    def __init__(self, server_url: str, timeout_seconds: float = 5.0) -> None:
        self._client = httpx.AsyncClient(base_url=server_url, timeout=timeout_seconds)

    async def publish_batch(self, batch: EventBatch) -> bool:
        try:
            response = await self._client.post("/api/events", json={"events": batch})
            response.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            logger.warning("事件上报失败（进入离线缓存）: {}", exc)
            return False

    async def close(self) -> None:
        await self._client.aclose()
