"""监控中心测试：帧缓冲 / 状态派生 / Overlay / Replay / Label / API。"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from agent.events.bus import EventBus
from agent.events.types import PresenceSleeping, SeatOccupied, SmokingEnded, SmokingStarted
from agent.monitor.annotator import OverlayToggles, annotate, hand_mouth_distance
from agent.monitor.api import create_monitor_app
from agent.monitor.config import MonitorSettings
from agent.monitor.frame_buffer import FrameBuffer
from agent.monitor.hub import MonitorHub
from agent.vision.frame import Box, Detection, Frame, HandFeatures, PoseFeatures, VisionContext


def _frame(timestamp: float) -> Frame:
    return Frame(
        image=np.full((32, 32, 3), 50, dtype=np.uint8), timestamp=timestamp, index=int(timestamp)
    )


def _context(timestamp: float) -> VisionContext:
    return VisionContext(
        frame=_frame(timestamp),
        detections=[Detection(0, "person", 0.9, Box(1, 1, 10, 10))],
        pose=PoseFeatures(
            mouth_box=Box(10, 10, 20, 18),
            hands=[
                HandFeatures(wrist=(0, 30), thumb_tip=(15, 14), index_tip=(0, 0), middle_tip=(0, 0))
            ],
        ),
    )


@pytest.fixture
def hub(tmp_path: Path) -> tuple[MonitorHub, EventBus]:
    bus = EventBus()
    settings = MonitorSettings(enabled=True, data_dir=str(tmp_path), replay_after_seconds=0.05)
    monitor_hub = MonitorHub("dev-1", settings, bus)
    monitor_hub.register_plugins(["smoking"])
    return monitor_hub, bus


class TestFrameBuffer:
    def test_窗口淘汰(self) -> None:
        buffer = FrameBuffer(capacity_seconds=10)
        for i in range(20):
            buffer.add(_frame(float(i)))
        assert buffer.latest() is not None
        assert buffer.latest().timestamp == 19.0  # type: ignore[union-attr]
        assert len(buffer.window(0, 100)) == 11  # 最近 10 秒窗口：t=9..19

    def test_window按时间过滤(self) -> None:
        buffer = FrameBuffer(capacity_seconds=100)
        for i in range(10):
            buffer.add(_frame(float(i)))
        assert [f.timestamp for f in buffer.window(3, 5)] == [3.0, 4.0, 5.0]


class TestAnnotator:
    def test_距离计算(self) -> None:
        pose = _context(0).pose
        measured = hand_mouth_distance(pose)
        assert measured is not None
        dist, _, _ = measured
        assert dist < 10  # thumb_tip(15,14) 距嘴中心(15,14) 约 0

    def test_无脸返回None(self) -> None:
        assert hand_mouth_distance(PoseFeatures()) is None

    def test_annotate不修改原图(self) -> None:
        context = _context(0)
        original = context.frame.image.copy()
        result = annotate(context.frame.image, context, OverlayToggles(), "working", "5 fps", "evt")
        assert result.shape == original.shape
        assert np.array_equal(context.frame.image, original)

    def test_开关更新(self) -> None:
        toggles = OverlayToggles()
        toggles.update({"face": False, "unknown": True})
        assert toggles.face is False
        assert "unknown" not in toggles.as_dict()


class TestHub:
    async def test_事件派生状态(self, hub: tuple[MonitorHub, EventBus]) -> None:
        monitor_hub, bus = hub
        await bus.publish(SeatOccupied(device_id="dev-1"))
        snapshot = monitor_hub.state_snapshot()
        assert snapshot["behavior"]["presence"] == "working"
        assert snapshot["plugins"] == [{"name": "smoking", "status": "running"}]

        await bus.publish(SmokingStarted(device_id="dev-1"))
        assert monitor_hub.state_snapshot()["behavior"]["current"] == "smoking"

        await bus.publish(PresenceSleeping(device_id="dev-1"))
        snapshot = monitor_hub.state_snapshot()
        assert snapshot["behavior"]["presence"] == "sleeping"
        assert snapshot["plugins"][0]["status"] == "suspended"
        assert snapshot["behavior"]["current"] == "idle"  # 休眠清空行为

    async def test_时间轴记录(self, hub: tuple[MonitorHub, EventBus]) -> None:
        monitor_hub, bus = hub
        await bus.publish(SeatOccupied(device_id="dev-1"))
        await bus.publish(SmokingEnded(device_id="dev-1", duration_seconds=120.0))
        events = monitor_hub.timeline()
        assert [e["event_type"] for e in events] == ["SeatOccupied", "SmokingEnded"]
        assert events[1]["payload"]["duration_seconds"] == 120.0

    async def test_帧钩子渲染(self, hub: tuple[MonitorHub, EventBus]) -> None:
        monitor_hub, _ = hub
        monitor_hub.on_frame(_context(1000.0))
        jpeg = monitor_hub.render_jpeg()
        assert jpeg is not None and jpeg[:2] == b"\xff\xd8"  # JPEG 魔数

    async def test_snapshot保存(self, hub: tuple[MonitorHub, EventBus]) -> None:
        monitor_hub, _ = hub
        monitor_hub.on_frame(_context(1000.0))
        result = monitor_hub.save_snapshot()
        assert result is not None
        assert Path(result["image"]).exists()
        meta = json.loads(Path(result["meta"]).read_text(encoding="utf-8"))
        assert meta["device_id"] == "dev-1"

    async def test_replay触发(self, hub: tuple[MonitorHub, EventBus]) -> None:
        monitor_hub, bus = hub
        now = time.time()
        for i in range(5):
            monitor_hub.on_frame(_context(now - 2 + i * 0.1))
        event = SmokingStarted(device_id="dev-1")
        await bus.publish(event)
        # replay_after_seconds=0.05，等待异步截取完成
        await asyncio.sleep(0.5)
        replays = monitor_hub.replay.list_replays()
        assert len(replays) == 1
        assert replays[0]["event_type"] == "SmokingStarted"
        snapshots = replays[0]["snapshots"]
        assert isinstance(snapshots, list) and len(snapshots) >= 1
        assert monitor_hub.replay.snapshot_path(event.event_id, snapshots[0]) is not None

    def test_label_mode(self, hub: tuple[MonitorHub, EventBus]) -> None:
        monitor_hub, _ = hub
        record = monitor_hub.record_label("abc", "wrong", note="误判")
        assert record["verdict"] == "wrong"
        with pytest.raises(ValueError, match="correct/wrong"):
            monitor_hub.record_label("abc", "maybe")


class TestApi:
    async def test_端点可用(self, hub: tuple[MonitorHub, EventBus]) -> None:
        monitor_hub, bus = hub
        monitor_hub.on_frame(_context(1000.0))
        await bus.publish(SeatOccupied(device_id="dev-1"))
        client = TestClient(create_monitor_app(monitor_hub))

        state = client.get("/monitor/state")
        assert state.status_code == 200
        assert state.json()["behavior"]["presence"] == "working"

        events = client.get("/monitor/events")
        assert events.json()["events"][0]["event_type"] == "SeatOccupied"

        image = client.get("/monitor/snapshot.png")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/jpeg"

        toggles = client.post("/monitor/overlays", json={"face": False})
        assert toggles.json()["face"] is False

        label = client.post("/monitor/labels", json={"event_id": "x", "verdict": "correct"})
        assert label.status_code == 200

        assert client.get("/monitor/replays").status_code == 200
        assert client.get("/monitor/replays/nope/frames/0000.jpg").status_code == 404
