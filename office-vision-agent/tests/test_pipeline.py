"""VisionPipeline 测试：用假摄像头/检测器驱动，验证事件流与休眠联动。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from agent.events.bus import EventBus
from agent.events.types import Event, SeatOccupied
from agent.plugins.manager import PluginManager
from agent.presence.manager import PresenceManager, PresenceSettings
from agent.vision.camera.base import BaseCamera
from agent.vision.detector.base import BaseDetector, BasePoseDetector
from agent.vision.frame import Box, Detection, Frame, HandFeatures, PoseFeatures
from agent.vision.pipeline import VisionPipeline

PLUGINS_ROOT = Path(__file__).resolve().parent.parent / "plugins"


class FakeCamera(BaseCamera):
    name = "fake"

    def __init__(self) -> None:
        self.opened = False
        self.closed = False

    def start(self) -> bool:
        self.opened = True
        return True

    def read(self) -> Frame | None:
        return None

    def stop(self) -> None:
        self.closed = True

    @property
    def is_open(self) -> bool:
        return self.opened


class FakeDetector(BaseDetector):
    """可控制是否检测到人的假检测器。"""

    name = "fake"

    def __init__(self) -> None:
        self.person = False
        self.calls = 0

    def detect(self, frame: Frame) -> list[Detection]:
        self.calls += 1
        if not self.person:
            return []
        return [Detection(class_id=0, label="person", confidence=0.9, box=Box(0, 0, 10, 10))]


class FakePose(BasePoseDetector):
    """返回夹烟手势命中的假姿态（让 smoking 插件能触发），手腕高度可控。"""

    name = "fake"

    def __init__(self) -> None:
        self.calls = 0
        self.closed = False
        self.wrist_y = 26.0  # 嘴部区域外扩后 y 7..28，26=放下 8=举起

    def analyze(self, frame: Frame) -> PoseFeatures:
        self.calls += 1
        return PoseFeatures(
            mouth_box=Box(10, 10, 30, 25),
            hands=[
                HandFeatures(
                    wrist=(15, self.wrist_y),
                    thumb_tip=(18, 16),
                    index_tip=(20, 17),
                    middle_tip=(24, 18),
                )
            ],
        )

    def close(self) -> None:
        self.closed = True


def _frame(timestamp: float, index: int) -> Frame:
    return Frame(image=np.zeros((64, 64, 3), dtype=np.uint8), timestamp=timestamp, index=index)


@pytest.fixture
def rig() -> tuple[VisionPipeline, FakeDetector, FakePose, list[Event]]:
    bus = EventBus()
    camera = FakeCamera()
    detector = FakeDetector()
    pose = FakePose()
    presence = PresenceManager(
        "dev-1",
        PresenceSettings(sleep_after_seconds=20, resume_wait_seconds=2),
    )
    plugins = PluginManager(PLUGINS_ROOT, device_id="dev-1")
    plugins.load_all()
    pipeline = VisionPipeline(camera, detector, pose, presence, plugins, bus)
    received: list[Event] = []

    async def collect(event: Event) -> None:
        received.append(event)

    bus.subscribe(Event, collect)
    return pipeline, detector, pose, received


class TestProcessFrame:
    async def test_人出现_发SeatOccupied并运行姿态与插件(
        self, rig: tuple[VisionPipeline, FakeDetector, FakePose, list[Event]]
    ) -> None:
        pipeline, detector, pose, received = rig
        detector.person = True
        await pipeline._process_frame(_frame(100.0, 1))
        assert [type(e) for e in received] == [SeatOccupied]
        assert pose.calls == 1  # WORKING 时运行姿态分析

    async def test_夹烟手势加往返运动_插件产出SmokingStarted(
        self, rig: tuple[VisionPipeline, FakeDetector, FakePose, list[Event]]
    ) -> None:
        pipeline, detector, pose, received = rig
        detector.person = True
        # 手腕 y 序列：模拟举起→放下的往返动作
        ys = [26.0, 8.0, 8.0, 8.0, 26.0, 26.0, 26.0, 26.0]
        for i, y in enumerate(ys):
            pose.wrist_y = y
            await pipeline._process_frame(_frame(100.0 + i * 0.5, i + 1))
        types = [type(e).__name__ for e in received]
        assert "SmokingStarted" in types

    async def test_无人时不运行姿态(
        self, rig: tuple[VisionPipeline, FakeDetector, FakePose, list[Event]]
    ) -> None:
        pipeline, detector, pose, _ = rig
        detector.person = False
        await pipeline._process_frame(_frame(100.0, 1))
        assert pose.calls == 0

    async def test_完整休眠与恢复周期(
        self, rig: tuple[VisionPipeline, FakeDetector, FakePose, list[Event]]
    ) -> None:
        pipeline, detector, pose, received = rig
        detector.person = True
        await pipeline._process_frame(_frame(100.0, 1))  # WORKING
        detector.person = False
        await pipeline._process_frame(_frame(105.0, 2))  # 人离开 → AWAY (SeatEmpty)
        await pipeline._process_frame(_frame(120.0, 3))  # 仍无人，保持 AWAY
        pose_calls_at_away = pose.calls
        await pipeline._process_frame(_frame(145.0, 4))  # 超 sleep → SLEEPING
        types = [type(e).__name__ for e in received]
        assert "PresenceSleeping" in types
        assert not pipeline._plugins.detectors[0].enabled  # 插件已停用
        await pipeline._process_frame(_frame(150.0, 5))  # 休眠中，无人
        assert pose.calls == pose_calls_at_away  # 休眠期间不跑姿态
        detector.person = True
        await pipeline._process_frame(_frame(160.0, 6))  # 首次见到人
        await pipeline._process_frame(_frame(163.0, 7))  # 稳定 > resume_wait → 恢复
        assert "PresenceResumed" in [type(e).__name__ for e in received]
        assert pipeline._plugins.detectors[0].enabled  # 插件已恢复


class TestLifecycle:
    def test_open与shutdown(
        self, rig: tuple[VisionPipeline, FakeDetector, FakePose, list[Event]]
    ) -> None:
        pipeline, _, pose, _ = rig
        assert pipeline.open() is True
        pipeline.shutdown()
        assert pose.closed is True
        camera = pipeline._camera
        assert isinstance(camera, FakeCamera)
        assert camera.closed is True
