"""Transport 测试：离线缓存队列 + 推送器的失败重试/顺序保证。"""

from __future__ import annotations

from pathlib import Path

from agent.events.bus import EventBus
from agent.events.types import SeatEmpty, SeatOccupied
from agent.transport.base import EventBatch, EventPublisher
from agent.transport.offline_store import OfflineStore
from agent.transport.pusher import EventPusher


class FakePublisher(EventPublisher):
    """可控成功/失败的假上报通道。"""

    name = "fake"

    def __init__(self) -> None:
        self.ok = True
        self.batches: list[EventBatch] = []

    async def publish_batch(self, batch: EventBatch) -> bool:
        if not self.ok:
            return False
        self.batches.append(batch)
        return True


async def test_offline_store_fifo(tmp_path: Path) -> None:
    store = OfflineStore(tmp_path / "cache.db")
    await store.open()
    await store.append(
        [{"event_id": "a", "occurred_at": "t1"}, {"event_id": "b", "occurred_at": "t2"}]
    )
    assert await store.count() == 2
    rows = await store.pending(limit=10)
    assert [event["event_id"] for _, event in rows] == ["a", "b"]
    await store.remove([rows[0][0]])
    assert await store.count() == 1
    await store.close()


async def test_推送成功清空队列(tmp_path: Path) -> None:
    bus = EventBus()
    store = OfflineStore(tmp_path / "cache.db")
    publisher = FakePublisher()
    pusher = EventPusher(publisher, store, bus, push_interval_seconds=0.5)
    await pusher.start()

    await bus.publish(SeatOccupied(device_id="d"))
    await bus.publish(SeatEmpty(device_id="d"))
    assert await store.count() == 2

    assert await pusher.flush_once() is True
    assert await store.count() == 0
    assert [e["event_type"] for batch in publisher.batches for e in batch] == [
        "SeatOccupied",
        "SeatEmpty",
    ]
    await pusher.stop()


async def test_失败保留队列_恢复后补齐(tmp_path: Path) -> None:
    bus = EventBus()
    store = OfflineStore(tmp_path / "cache.db")
    publisher = FakePublisher()
    pusher = EventPusher(publisher, store, bus)
    await pusher.start()

    await bus.publish(SeatOccupied(device_id="d"))
    publisher.ok = False
    assert await pusher.flush_once() is False  # 上报失败
    assert await store.count() == 1  # 事件不丢

    publisher.ok = True
    assert await pusher.flush_once() is True  # 恢复后自动同步
    assert await store.count() == 0
    assert publisher.batches[0][0]["event_type"] == "SeatOccupied"
    await pusher.stop()


async def test_离线期间事件持续入队(tmp_path: Path) -> None:
    bus = EventBus()
    store = OfflineStore(tmp_path / "cache.db")
    publisher = FakePublisher()
    publisher.ok = False
    pusher = EventPusher(publisher, store, bus)
    await pusher.start()

    for _ in range(5):
        await bus.publish(SeatOccupied(device_id="d"))
    await pusher.flush_once()
    assert await store.count() == 5  # 全部保留

    publisher.ok = True
    await pusher.flush_once()
    assert await store.count() == 0
    assert sum(len(b) for b in publisher.batches) == 5
    await pusher.stop()
