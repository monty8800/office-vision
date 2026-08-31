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
from datetime import datetime
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
    wakeup_check_seconds: float = 300.0  # 深度休眠（摄像头已关）时，每隔多久唤醒查一次人
    # --- 凌晨关闭窗口（本地时间）---
    off_hours_start: str = "00:00"          # 窗口开始（如 00:00）
    off_hours_end: str = "08:00"            # 窗口结束（8 点准时开启）
    off_hours_idle_seconds: float = 3600.0  # 窗口内无人连续多久后关摄像头（1 小时）


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
        self._entry_time: float | None = None  # 首次喂帧时刻，用于"启动即无人"超时休眠
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

    @property
    def wakeup_check_seconds(self) -> float:
        """深度休眠（摄像头已关）时周期性唤醒查人的间隔（秒）。"""
        return self._settings.wakeup_check_seconds

    @property
    def resume_wait_seconds(self) -> float:
        """恢复到 Working 前，需要人员持续在场的秒数。"""
        return self._settings.resume_wait_seconds

    # ---- 凌晨关闭窗口（时间感知） ----

    @staticmethod
    def _hhmm(s: str) -> int:
        try:
            h, m = s.split(":", 1)[:2]
            return int(h) * 60 + int(m)
        except Exception:
            return 0

    def _in_off_hours(self, timestamp: float) -> bool:
        """当前本地时间是否落在凌晨关闭窗口内。"""
        local = datetime.fromtimestamp(timestamp).astimezone()
        cur = local.hour * 60 + local.minute
        return self._hhmm(self._settings.off_hours_start) <= cur < self._hhmm(
            self._settings.off_hours_end
        )

    def sleep_after(self, timestamp: float) -> float:
        """无人连续多久后进入休眠：凌晨窗口用 off_hours_idle_seconds，其余用 sleep_after_seconds。"""
        return (
            self._settings.off_hours_idle_seconds
            if self._in_off_hours(timestamp)
            else self._settings.sleep_after_seconds
        )

    def past_off_hours_end(self, timestamp: float) -> bool:
        """当前本地时间是否已过凌晨窗口结束点（如是否已到 08:00）。"""
        local = datetime.fromtimestamp(timestamp).astimezone()
        cur = local.hour * 60 + local.minute
        return cur >= self._hhmm(self._settings.off_hours_end)

    def force_wake(self) -> list[Event]:
        """外部（如 08:00）强制唤醒：SLEEPING → AWAY，摄像头保持开启等待人。"""
        if self._state is PresenceState.SLEEPING:
            self._state = PresenceState.AWAY
            self._return_first_seen = None
            return [PresenceResumed(device_id=self._device_id)]
        return []

    def update(self, person_present: bool, timestamp: float) -> list[Event]:
        """喂入单帧人员判定，返回本帧产出的 Presence 事件。"""
        if self._entry_time is None:
            self._entry_time = timestamp
        if person_present:
            self._last_seen = timestamp
        elif self._last_seen <= 0.0:
            # 从未真实见到人时，用启动时刻作"最后见人"基准，避免
            # _from_away 里 timestamp-0.0>=sleep_after 恒成立而瞬间休眠、来回振荡刷事件
            self._last_seen = self._entry_time or timestamp
        if self._state is PresenceState.WAITING:
            return self._from_waiting(person_present, timestamp)
        if self._state is PresenceState.WORKING:
            return self._from_working(person_present, timestamp)
        if self._state is PresenceState.AWAY:
            return self._from_away(person_present, timestamp)
        return self._from_sleeping(person_present, timestamp)

    # ---- 各状态迁移 ----

    def _from_waiting(self, present: bool, timestamp: float) -> list[Event]:
        if present:
            self._state = PresenceState.WORKING
            return [SeatOccupied(device_id=self._device_id)]
        if timestamp - (self._entry_time or timestamp) >= self.sleep_after(timestamp):
            self._state = PresenceState.SLEEPING
            return [PresenceSleeping(device_id=self._device_id)]
        return []

    def _from_working(self, present: bool, timestamp: float) -> list[Event]:
        if present:
            return []
        self._state = PresenceState.AWAY
        return [SeatEmpty(device_id=self._device_id)]

    def _from_away(self, present: bool, timestamp: float) -> list[Event]:
        if present:
            self._state = PresenceState.WORKING
            return [SeatOccupied(device_id=self._device_id)]
        if timestamp - self._last_seen >= self.sleep_after(timestamp):
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
