"""Smoking Detector 插件入口。

插件规范：暴露 create_detector(device_id, config) -> BaseBehaviorDetector。
插件只产出事件（SmokingStarted / SmokingEnded），不直接操作数据库、不上报网络。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import fields
from typing import Any

from detector import SmokingConfig, SmokingSessionMachine, SmokingSignal, evaluate_frame

from agent.events.types import Event
from agent.vision.behavior.base import BaseBehaviorDetector
from agent.vision.frame import VisionContext


class SmokingDetector(BaseBehaviorDetector):
    """抽烟行为检测器。"""

    name = "smoking"

    def __init__(self, device_id: str, config: dict[str, Any] | None = None) -> None:
        super().__init__(device_id, config)
        valid_keys = {f.name for f in fields(SmokingConfig)}
        filtered = {k: v for k, v in self.config.items() if k in valid_keys}
        self._smoking_config = SmokingConfig(**filtered)
        self._machine = SmokingSessionMachine(self._smoking_config, device_id)
        self._last_signal = SmokingSignal(hit=False)
        self._last_cigarette_visible = False
        self._last_timestamp = 0.0

    @property
    def state(self) -> str:
        return self._machine.state.value

    def on_frame(self, context: VisionContext) -> Sequence[Event]:
        signal = evaluate_frame(context.pose, self._smoking_config)
        self._last_signal = signal
        self._last_timestamp = context.frame.timestamp
        # 自训练香烟检测框作为强证据（无模型时 detections 里永远不会有 cigarette）
        cigarette_visible = any(d.label == "cigarette" for d in context.detections)
        self._last_cigarette_visible = cigarette_visible
        return self._machine.update(signal, context.frame.timestamp, cigarette_visible)

    def debug_info(self) -> dict[str, Any]:
        info = self._machine.debug_info(self._last_timestamp)
        info["signal"] = {
            "hit": self._last_signal.hit,
            "index_near": self._last_signal.index_near,
            "grip": self._last_signal.grip,
            "cigarette_visible": self._last_cigarette_visible,
        }
        return info

    def disable(self) -> None:
        super().disable()
        self._machine.reset()  # 休眠时未结束的会话直接丢弃，避免跨休眠误计


def create_detector(device_id: str, config: dict[str, Any]) -> SmokingDetector:
    """插件工厂：由 PluginManager 调用。"""
    return SmokingDetector(device_id, config)
