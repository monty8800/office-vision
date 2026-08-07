"""PresenceManager：统一管理人在/离开/休眠/恢复。

所有插件只监听 Presence 事件，不自行判断人在不在。

状态机:
    Waiting → (检测到人) → Working                    发 SeatOccupied
    Working → (人离开画面) → Away                     发 SeatEmpty
    Away → (人回来) → Working                         发 SeatOccupied
    Away → (超过 sleep_after_seconds 无人) → Sleeping 发 PresenceSleeping
        停止 MediaPipe / YOLO / 所有 Plugin，仅保留轻量 Presence 检测
    Sleeping → (人回来并稳定 resume_wait_seconds) → Working 发 PresenceResumed
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from agent.events.types import (
    Event,
    PresenceResumed,
    PresenceSleeping,
    SeatEmpty,
    SeatOccupied,
)


@dataclass(frozen=True)
class PresenceSettings:
    """Presence 参数（来自 config/agent.yaml 的 presence 段）。"""

    enabled: bool = True
    sleep_after_seconds: float = 300.0
    resume_wait_seconds: float = 3.0


class PresenceState(StrEnum):
    WAITING = "waiting"
    WORKING = "working"
    AWAY = "away"
    SLEEPING = "sleeping"


class PresenceManager:
    """纯状态机，可完全单元测试。update(person_present, timestamp) 每帧调用。"""

    def __init__(self, device_id: str, settings: PresenceSettings | None = None) -> None:
        self._device_id = device_id
        self._settings = settings or PresenceSettings()
        self._state = PresenceState.WAITING
        self._last_seen = 0.0
        self._return_first_seen: float | None = None

    @property
    def state(self) -> PresenceState:
        return self._state

    @property
    def run_full_pipeline(self) -> bool:
        """是否运行重量级组件（MediaPipe / 行为插件）。"""
        return self._state is PresenceState.WORKING

    @property
    def run_presence_detection(self) -> bool:
        """是否运行轻量 Presence 检测。恒为 True：休眠时也要低频检测以便唤醒。"""
        return True

    def update(self, person_present: bool, timestamp: float) -> list[Event]:
        """喂入单帧人员判定，返回本帧产出的 Presence 事件。"""
        if person_present:
            self._last_seen = timestamp
        if self._state is PresenceState.WAITING:
            return self._from_waiting(person_present)
        if self._state is PresenceState.WORKING:
            return self._from_working(person_present, timestamp)
        if self._state is PresenceState.AWAY:
            return self._from_away(person_present, timestamp)
        return self._from_sleeping(person_present, timestamp)

    # ---- 各状态迁移 ----

    def _from_waiting(self, present: bool) -> list[Event]:
        if not present:
            return []
        self._state = PresenceState.WORKING
        return [SeatOccupied(device_id=self._device_id)]

    def _from_working(self, present: bool, timestamp: float) -> list[Event]:
        if present:
            return []
        self._state = PresenceState.AWAY
        return [SeatEmpty(device_id=self._device_id)]

    def _from_away(self, present: bool, timestamp: float) -> list[Event]:
        if present:
            self._state = PresenceState.WORKING
            return [SeatOccupied(device_id=self._device_id)]
        if timestamp - self._last_seen >= self._settings.sleep_after_seconds:
            self._state = PresenceState.SLEEPING
            return [PresenceSleeping(device_id=self._device_id)]
        return []

    def _from_sleeping(self, present: bool, timestamp: float) -> list[Event]:
        if not present:
            self._return_first_seen = None
            return []
        if self._return_first_seen is None:
            self._return_first_seen = timestamp
            return []
        if timestamp - self._return_first_seen >= self._settings.resume_wait_seconds:
            self._state = PresenceState.WORKING
            self._return_first_seen = None
            return [PresenceResumed(device_id=self._device_id)]
        return []
