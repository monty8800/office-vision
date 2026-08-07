"""心跳任务：周期性发布 AgentAlive 事件。

Server 以"最近一次事件上报时间"判定 Agent 在线（60 秒阈值），
若只依赖业务事件，办公室安静期（无人活动/无行为发生）会被误判离线。
心跳与业务无关，仅证明进程存活。

链路复用：AgentAlive 经 EventBus → EventPusher → 离线队列 → HTTP，
与业务事件同等"不丢、不乱序"保证；Server 侧无需任何改动
（任何事件都会刷新该设备心跳）。
"""

from __future__ import annotations

import asyncio

from loguru import logger

from agent.events.bus import EventBus
from agent.events.types import AgentAlive


class HeartbeatTask:
    """每 interval 秒发布一条 AgentAlive；作为独立协程随主循环运行。"""

    def __init__(self, bus: EventBus, device_id: str, interval_seconds: float = 30.0) -> None:
        self._bus = bus
        self._device_id = device_id
        # 下限保护：心跳必须显著快于 Server 的 60 秒在线阈值
        self._interval = max(interval_seconds, 5.0)

    async def run(self) -> None:
        logger.info("心跳任务启动（间隔 {}s）", self._interval)
        while True:
            await self._bus.publish(AgentAlive(device_id=self._device_id))
            await asyncio.sleep(self._interval)
