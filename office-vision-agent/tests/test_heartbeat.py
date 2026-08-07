"""心跳任务测试：周期性 AgentAlive 发布与推送链路贯通。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from agent.events.bus import EventBus
from agent.events.types import AgentAlive, Event
from agent.transport.heartbeat import HeartbeatTask
from agent.transport.offline_store import OfflineStore
from agent.transport.pusher import EventPusher
from tests.test_transport import FakePublisher


async def test_心跳启动立即发布首拍() -> None:
    bus = EventBus()
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe(Event, handler)
    task = asyncio.create_task(HeartbeatTask(bus, "dev-1").run())
    await asyncio.sleep(0.05)  # 首拍在 run() 入口即发，无需等待间隔
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert [type(e) for e in received] == [AgentAlive]
    assert received[0].device_id == "dev-1"


async def test_心跳经推送链路上报(tmp_path: Path) -> None:
    bus = EventBus()
    store = OfflineStore(tmp_path / "cache.db")
    publisher = FakePublisher()
    pusher = EventPusher(publisher, store, bus)
    await pusher.start()

    task = asyncio.create_task(HeartbeatTask(bus, "dev-1").run())
    await asyncio.sleep(0.05)
    assert await pusher.flush_once() is True
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert publisher.batches[0][0]["event_type"] == "AgentAlive"
    await pusher.stop()
