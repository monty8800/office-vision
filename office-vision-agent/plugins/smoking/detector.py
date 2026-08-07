"""抽烟检测核心逻辑：夹烟手势 + 往返运动模式 + 会话状态机 + 香烟检出融合。

纯逻辑模块（不依赖 OpenCV/MediaPipe），可完全单元测试。

单帧命中三要素（全部满足才算命中一帧）：
1. 食指指尖接近嘴部（夹烟特征；托手/捂嘴时通常不是食指主导）
2. 握持手势：拇指-食指指尖聚拢（夹持状），排除手掌摊开托下巴
3. 手腕进入嘴部外扩区域

进入 Smoking 还需会话级条件（排除"手一直放嘴上"的静态姿势）：
- 连续命中 min_hits_to_start 帧且持续 min_suspect_seconds 以上
- 窗口内检测到 min_round_trips 次"举起→放下"往返（真实抽烟的重复动作）

香烟检出（cigarette 目标检测）作为独立确认通道（主通道）：
- cigarette_confirm_window_seconds 窗口内检出达 cigarette_confirm_frames 次即确认抽烟，
  不依赖手势判据（实际画面中 MediaPipe 手势常因角度/遮挡无法达标，手势不应阻断强证据）
- 手势命中仍为无香烟检出时的降级通道，维持严格阈值

状态机:
    Idle → (手势命中或香烟连续检出) → Suspect → (任一通道达标) → Smoking
    Smoking → (超过 no_detection_timeout 无任何证据) → 结束会话 → Idle

一根烟只产出一条 SmokingEnded 记录，避免重复计数。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from agent.events.types import Event, SmokingEnded, SmokingStarted
from agent.vision.frame import PoseFeatures

PLUGIN_NAME = "smoking"


@dataclass(frozen=True)
class SmokingConfig:
    """抽烟检测参数（与 plugins/smoking/config.yaml 对应）。"""

    mouth_region_expand: float = 1.4
    grip_distance_ratio: float = 0.6
    min_hits_to_start: int = 8
    min_suspect_seconds: float = 3.0
    round_trip_window_seconds: float = 15.0
    min_round_trips: int = 1
    lift_fraction: float = 0.25
    max_misses_suspect: int = 8
    no_detection_timeout: float = 30.0
    min_duration: float = 5.0
    # --- 香烟检出独立确认通道（主通道）---
    cigarette_confirm_frames: int = 3  # 窗口内检出次数达标即确认
    cigarette_confirm_window_seconds: float = 3.0  # 检出计数的滚动窗口（容忍帧间闪烁）
    cigarette_min_seconds: float = 1.0  # 从首次检出起的最短观察时长
    cigarette_min_hits_to_start: int = 3  # 有香烟证据时手势通道的放宽阈值
    cigarette_min_suspect_seconds: float = 1.0
    cigarette_memory_seconds: float = 3.0  # 检出后多久内视为有效证据


class SmokingState(StrEnum):
    IDLE = "idle"
    SUSPECT = "suspect"
    SMOKING = "smoking"


@dataclass(frozen=True)
class SmokingSignal:
    """单帧抽烟手势评估结果。"""

    hit: bool
    index_near: bool = False
    grip: bool = False
    wrist_y: float | None = None


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def evaluate_frame(pose: PoseFeatures, config: SmokingConfig) -> SmokingSignal:
    """评估单帧是否呈现夹烟手势（食指近嘴 + 指尖聚拢 + 手腕入区）。

    未命中时也返回最接近命中的那只手的细节，供 Debug 面板诊断。
    """
    if pose.mouth_box is None or not pose.hands:
        return SmokingSignal(hit=False)
    region = pose.mouth_box.expand(config.mouth_region_expand)
    best = SmokingSignal(hit=False)
    for hand in pose.hands:
        index_near = region.contains(*hand.index_tip)
        mouth_size = max(pose.mouth_box.width, pose.mouth_box.height)
        grip = _distance(hand.thumb_tip, hand.index_tip) < mouth_size * config.grip_distance_ratio
        wrist_in = region.contains(*hand.wrist)
        signal = SmokingSignal(
            hit=index_near and grip and wrist_in,
            index_near=index_near,
            grip=grip,
            wrist_y=hand.wrist[1],
        )
        if signal.hit:
            return signal
        if (index_near, grip) > (best.index_near, best.grip):
            best = signal
    return best


def hand_near_mouth(pose: PoseFeatures, expand: float) -> bool:
    """宽松版手-嘴判定（Debug Overlay 距离标注用，非检测判据）。"""
    if pose.mouth_box is None or not pose.hands:
        return False
    region = pose.mouth_box.expand(expand)
    return any(region.contains(x, y) for hand in pose.hands for x, y in hand.fingertips)


def _to_datetime(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, UTC)


class SmokingSessionMachine:
    """抽烟会话状态机。update(signal, timestamp) 每帧调用一次。"""

    def __init__(self, config: SmokingConfig, device_id: str) -> None:
        self._config = config
        self._device_id = device_id
        self._state = SmokingState.IDLE
        self._hits = 0
        self._misses = 0
        self._session_start = 0.0
        self._last_hit = 0.0
        # 往返运动追踪（手腕 y：值越小越靠上）
        self._heights: list[tuple[float, float]] = []
        self._last_peak: float | None = None
        self._round_trips = 0
        self._last_cigarette_seen: float | None = None  # 最近一次检出香烟的时刻
        # 香烟独立通道：滚动窗口内的检出时刻序列
        self._cig_times: list[float] = []

    @property
    def state(self) -> SmokingState:
        return self._state

    def debug_info(self, timestamp: float) -> dict[str, object]:
        """状态机内部快照（Debug Center 诊断用）。"""
        return {
            "state": self._state.value,
            "hits": self._hits,
            "misses": self._misses,
            "round_trips": self._round_trips,
            "session_seconds": (
                round(timestamp - self._session_start, 1)
                if self._state is not SmokingState.IDLE
                else None
            ),
            "seconds_since_last_hit": (
                round(timestamp - self._last_hit, 1) if self._last_hit else None
            ),
            "seconds_since_cigarette": (
                round(timestamp - self._last_cigarette_seen, 1)
                if self._last_cigarette_seen is not None
                else None
            ),
            "cigarette_hits_recent": len(self._cig_times),
        }

    def reset(self) -> None:
        self._state = SmokingState.IDLE
        self._hits = 0
        self._misses = 0
        self._session_start = 0.0
        self._last_hit = 0.0
        self._heights = []
        self._last_peak = None
        self._round_trips = 0
        self._last_cigarette_seen = None
        self._cig_times = []

    def update(
        self, signal: SmokingSignal, timestamp: float, cigarette_visible: bool = False
    ) -> list[Event]:
        events: list[Event] = []
        if cigarette_visible:
            self._last_cigarette_seen = timestamp
            self._cig_times.append(timestamp)
        window = self._config.cigarette_confirm_window_seconds
        while self._cig_times and timestamp - self._cig_times[0] > window:
            self._cig_times.pop(0)

        # 超时收尾：手势与香烟均无证据才算沉寂（即使本帧命中也先判断，保证时间轴严格）
        cig_active = (
            timestamp - (self._last_cigarette_seen or 0.0) <= self._config.no_detection_timeout
        )
        if (
            self._state is SmokingState.SMOKING
            and timestamp - self._last_hit >= self._config.no_detection_timeout
            and not cig_active
        ):
            ended = self._finish_session(timestamp)
            if ended is not None:
                events.append(ended)

        # 香烟独立通道：窗口内检出达标即确认（不依赖手势）
        if (
            cigarette_visible
            and self._state is not SmokingState.SMOKING
            and len(self._cig_times) >= self._config.cigarette_confirm_frames
            and timestamp - self._cig_times[0] >= self._config.cigarette_min_seconds
        ):
            self._state = SmokingState.SMOKING
            if self._session_start <= 0.0:
                self._session_start = self._cig_times[0]
            self._last_hit = timestamp  # 香烟证据同样延续会话
            events.append(
                SmokingStarted(device_id=self._device_id, occurred_at=_to_datetime(timestamp))
            )
            return events

        if signal.hit:
            events.extend(self._on_hit(signal, timestamp))
        else:
            self._on_miss(timestamp)
        return events

    def _on_hit(self, signal: SmokingSignal, timestamp: float) -> list[Event]:
        self._misses = 0
        self._track_motion(signal.wrist_y, timestamp)
        if self._state is SmokingState.IDLE:
            self._state = SmokingState.SUSPECT
            self._hits = 1
            self._session_start = timestamp
            self._last_hit = timestamp
            return []
        if self._state is SmokingState.SUSPECT:
            self._hits += 1
            self._last_hit = timestamp
            if self._ready_to_confirm(timestamp):
                self._state = SmokingState.SMOKING
                return [
                    SmokingStarted(device_id=self._device_id, occurred_at=_to_datetime(timestamp))
                ]
            return []
        # SMOKING
        self._last_hit = timestamp
        return []

    def _cigarette_recent(self, timestamp: float) -> bool:
        """近 cigarette_memory_seconds 内是否检出过香烟（强证据窗口）。"""
        if self._last_cigarette_seen is None:
            return False
        return timestamp - self._last_cigarette_seen <= self._config.cigarette_memory_seconds

    def _ready_to_confirm(self, timestamp: float) -> bool:
        """进入 Smoking 的三重条件：命中数 + 持续时长 + 往返运动。

        近期检出香烟时放宽命中数/时长阈值（强证据加速确认），往返仍要求；
        窗口内香烟检出达标已由独立通道直接确认，此处仅覆盖手势通道。
        """
        if self._cigarette_recent(timestamp):
            min_hits = self._config.cigarette_min_hits_to_start
            min_seconds = self._config.cigarette_min_suspect_seconds
        else:
            min_hits = self._config.min_hits_to_start
            min_seconds = self._config.min_suspect_seconds
        if self._hits < min_hits:
            return False
        if timestamp - self._session_start < min_seconds:
            return False
        return self._round_trips >= self._config.min_round_trips

    def _track_motion(self, wrist_y: float | None, timestamp: float) -> None:
        """手腕 y 轨迹 → 往返计数：举起（y 降低超阈值）后回落即一次往返。"""
        if wrist_y is None or self._state is not SmokingState.SUSPECT:
            return
        self._heights.append((timestamp, wrist_y))
        window = self._config.round_trip_window_seconds
        while self._heights and timestamp - self._heights[0][0] > window:
            self._heights.pop(0)
        ys = [y for _, y in self._heights]
        baseline = max(ys)  # 最低点（y 最大）
        amplitude = baseline - min(ys)
        lift_threshold = self._config.lift_fraction * max(amplitude, 1.0)
        for _, y in reversed(self._heights):
            if baseline - y >= lift_threshold:
                recent_peak = y
                break
        else:
            recent_peak = None
        if recent_peak is None:
            self._last_peak = None
            return
        if self._last_peak is None:
            self._last_peak = recent_peak
        elif wrist_y >= self._last_peak + lift_threshold:
            # 曾举到 peak 高度，现已回落 → 完成一次往返，从当前位置重新追踪
            self._round_trips += 1
            self._last_peak = None
            self._heights = [(timestamp, wrist_y)]

    def _on_miss(self, timestamp: float) -> None:
        if self._state is SmokingState.SUSPECT:
            self._misses += 1
            if self._misses > self._config.max_misses_suspect:
                self.reset()
            elif timestamp - self._last_hit > self._config.round_trip_window_seconds:
                self.reset()  # 会话拖太久未确认，丢弃旧轨迹重新观察

    def _finish_session(self, timestamp: float) -> SmokingEnded | None:
        duration = timestamp - self._session_start
        start = self._session_start
        self.reset()
        if duration < self._config.min_duration:
            return None  # 过短会话视为误报
        return SmokingEnded(
            device_id=self._device_id,
            occurred_at=_to_datetime(timestamp),
            start_time=_to_datetime(start),
            end_time=_to_datetime(timestamp),
            duration_seconds=duration,
        )
