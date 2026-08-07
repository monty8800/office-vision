"""BaseBehaviorDetector：所有行为识别的抽象基类。

开闭原则：新增行为（DrinkingDetector / PhoneDetector / AwayDetector /
FatigueDetector）只需新增子类与插件目录，禁止修改已有 Detector。

行为检测器只做一件事：消费视觉上下文，产出领域事件。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

from agent.events.types import Event
from agent.vision.frame import VisionContext


class BaseBehaviorDetector(ABC):
    """行为检测器基类。"""

    #: 插件唯一名称（与插件目录名一致）
    name: str = "base"

    def __init__(self, device_id: str, config: dict[str, Any] | None = None) -> None:
        self.device_id = device_id
        self.config = config or {}
        self.enabled = True

    @abstractmethod
    def on_frame(self, context: VisionContext) -> Sequence[Event]:
        """处理单帧视觉上下文，返回零或多个领域事件。"""

    def enable(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        """休眠时由 PluginManager 调用；子类可覆写以重置内部状态。"""
        self.enabled = False

    def debug_info(self) -> dict[str, Any]:
        """供 Debug Center 展示的内部状态快照；子类可覆写。"""
        return {}
