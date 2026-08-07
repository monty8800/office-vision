"""PluginManager 测试：加载真实 plugins/smoking 插件并验证生命周期。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from agent.events.types import SmokingStarted
from agent.plugins.manager import PluginManager
from agent.vision.frame import Box, Frame, HandFeatures, PoseFeatures, VisionContext

PLUGINS_ROOT = Path(__file__).resolve().parent.parent / "plugins"


@pytest.fixture
def manager() -> PluginManager:
    pm = PluginManager(PLUGINS_ROOT, device_id="dev-1")
    pm.load_all()
    return pm


def _context_with_hit(timestamp: float, wrist_y: float = 26.0) -> VisionContext:
    """构造夹烟手势命中的上下文：食指近嘴 + 指尖聚拢 + 手腕入区。"""
    image = np.zeros((64, 64, 3), dtype=np.uint8)
    frame = Frame(image=image, timestamp=timestamp, index=int(timestamp))
    pose = PoseFeatures(
        mouth_box=Box(10, 10, 30, 25),
        hands=[
            HandFeatures(
                wrist=(15, wrist_y), thumb_tip=(18, 16), index_tip=(20, 17), middle_tip=(24, 18)
            )
        ],
    )
    return VisionContext(frame=frame, pose=pose)


class TestLoad:
    def test_加载smoking插件(self, manager: PluginManager) -> None:
        assert manager.names == ["smoking"]

    def test_目录不存在_返回空(self) -> None:
        pm = PluginManager(Path("/nonexistent/plugins"), device_id="d")
        assert pm.load_all() == []

    def test_插件配置来自config_yaml(self, manager: PluginManager) -> None:
        detector = manager.detectors[0]
        assert detector.config.get("min_hits_to_start") == 8


class TestLifecycle:
    def test_suspend后不再产出事件(self, manager: PluginManager) -> None:
        manager.suspend()
        events = manager.process_frame(_context_with_hit(1000.0))
        assert events == []

    def test_resume后恢复(self, manager: PluginManager) -> None:
        manager.suspend()
        manager.resume()
        assert manager.detectors[0].enabled is True

    def test_休眠会丢弃未结束会话(self, manager: PluginManager) -> None:
        # 累计 5 次命中（阈值 8，尚未触发）
        for i in range(5):
            manager.process_frame(_context_with_hit(1000.0 + i * 0.5))
        manager.suspend()  # 休眠 → reset
        manager.resume()
        events = []
        for i in range(5):
            events.extend(manager.process_frame(_context_with_hit(1010.0 + i * 0.5)))
        assert events == []  # 重新计数，5 < 8 不应触发

    def test_命中加往返运动产出SmokingStarted(self, manager: PluginManager) -> None:
        # 手腕 y：26=放下 8=举起（嘴部区域 y 7..28），模拟举起→放下往返
        ys = [26.0, 8.0, 8.0, 8.0, 26.0, 26.0, 26.0, 26.0]
        events = []
        for i, y in enumerate(ys):
            events.extend(manager.process_frame(_context_with_hit(1000.0 + i * 0.5, wrist_y=y)))
        assert [type(e) for e in events] == [SmokingStarted]

    def test_静态手放嘴上_不产出SmokingStarted(self, manager: PluginManager) -> None:
        # 手腕始终停在同一高度（托手/思考姿势）→ 无往返，不应确认
        events = []
        for i in range(20):
            events.extend(manager.process_frame(_context_with_hit(1000.0 + i * 0.5)))
        assert events == []
