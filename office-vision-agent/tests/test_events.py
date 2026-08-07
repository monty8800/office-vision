"""EventBus 与事件契约测试。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agent.events.bus import EventBus
from agent.events.types import (
    EVENT_REGISTRY,
    AgentAlive,
    Event,
    PersonDetected,
    SeatEmpty,
    SeatOccupied,
    SmokingEnded,
    event_from_dict,
)


class TestEventContract:
    def test_to_dict_包含全部契约字段(self) -> None:
        event = SeatOccupied(device_id="dev-1")
        data = event.to_dict()
        assert set(data) == {"event_id", "device_id", "event_type", "occurred_at", "payload"}
        assert data["event_type"] == "SeatOccupied"
        assert data["device_id"] == "dev-1"
        assert data["payload"] == {}

    def test_smoking_ended_payload_携带会话信息(self) -> None:
        start = datetime(2026, 8, 6, 10, 0, tzinfo=UTC)
        end = datetime(2026, 8, 6, 10, 3, 20, tzinfo=UTC)
        event = SmokingEnded(
            device_id="dev-1",
            occurred_at=end,
            start_time=start,
            end_time=end,
            duration_seconds=200.0,
        )
        payload = event.payload()
        assert payload["duration_seconds"] == 200.0
        assert payload["start_time"] == start.isoformat()

    def test_registry_覆盖全部事件类型(self) -> None:
        assert len(EVENT_REGISTRY) == 9
        assert "SmokingEnded" in EVENT_REGISTRY
        assert "AgentAlive" in EVENT_REGISTRY


class TestEventRoundTrip:
    @pytest.mark.parametrize("cls", [PersonDetected, SeatOccupied, SeatEmpty, AgentAlive])
    def test_普通事件往返(self, cls: type[Event]) -> None:
        original = cls(device_id="dev-1")
        restored = event_from_dict(original.to_dict())
        assert type(restored) is cls
        assert restored.event_id == original.event_id
        assert restored.device_id == "dev-1"
        assert restored.occurred_at == original.occurred_at

    def test_smoking_ended_往返(self) -> None:
        original = SmokingEnded(
            device_id="dev-1",
            start_time=datetime(2026, 8, 6, 10, 0, tzinfo=UTC),
            end_time=datetime(2026, 8, 6, 10, 5, tzinfo=UTC),
            duration_seconds=300.0,
        )
        restored = event_from_dict(original.to_dict())
        assert isinstance(restored, SmokingEnded)
        assert restored.duration_seconds == 300.0
        assert restored.start_time == original.start_time

    def test_未知类型报错(self) -> None:
        with pytest.raises(ValueError, match="未知事件类型"):
            event_from_dict({"event_type": "NoSuchEvent", "occurred_at": "2026-01-01T00:00:00"})


class TestEventBus:
    async def test_精确类型订阅(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def handler(event: SeatOccupied) -> None:
            received.append(event)

        bus.subscribe(SeatOccupied, handler)
        await bus.publish(SeatOccupied(device_id="d"))
        await bus.publish(SeatEmpty(device_id="d"))
        assert len(received) == 1

    async def test_基类订阅接收全部(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe(Event, handler)
        await bus.publish(SeatOccupied(device_id="d"))
        await bus.publish(SeatEmpty(device_id="d"))
        assert len(received) == 2

    async def test_同步处理器(self) -> None:
        bus = EventBus()
        seen: list[str] = []
        bus.subscribe_sync(SeatOccupied, lambda e: seen.append(e.event_type))
        await bus.publish(SeatOccupied(device_id="d"))
        assert seen == ["SeatOccupied"]

    async def test_处理器异常隔离(self) -> None:
        bus = EventBus()
        ok: list[bool] = []

        async def bad(_: Event) -> None:
            raise RuntimeError("boom")

        async def good(_: Event) -> None:
            ok.append(True)

        bus.subscribe(Event, bad)
        bus.subscribe(Event, good)
        await bus.publish(SeatOccupied(device_id="d"))
        assert ok == [True]
