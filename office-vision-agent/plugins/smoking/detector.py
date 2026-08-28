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
  不依赖完整手势判据（实际画面中 MediaPipe 手势常因角度/遮挡无法达标，手势不应阻断强证据）
- 但独立通道需最低手势佐证（窗口内至少 cigarette_min_gesture_frames 帧食指近嘴）：
  香烟模型会把笔/手表/耳朵鼻子误检为香烟且持续高置信度，真实抽烟必然伴随
  手靠近嘴部，完全无手势证据的持续检出一律视为误检
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
from agent.vision.frame import Box, PoseFeatures

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
    cigarette_min_gesture_frames: int = 1  # 独立通道所需的最少食指近嘴帧数（防误检）
    # --- 香烟位置判据（用户规则：烟在手中或嘴里才算抽烟，放桌上不算）---
    # 香烟框中心须落入「嘴部外扩区」多少次（滚动窗口内）视为"在嘴里"的强证据
    cig_in_mouth_confirm_frames: int = 2
    # 香烟框中心距"近嘴的手"关键点的最大距离（相对嘴部尺寸）
    cig_in_hand_proximity: float = 2.0
    # --- 行为分类确认通道（smoking-cls，默认关闭：模型不可靠，被位置规则取代）---
    classifier_confirm_frames: int = 0  # 窗口内分类为 smoking 的最少帧数（0=关闭该通道）
    classifier_min_conf: float = 0.6  # 判定为 smoking 所需的最小分类置信度


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


@dataclass(frozen=True)
class CigaretteSignal:
    """单帧香烟检出 + 位置判据（用户规则：烟在手中/嘴里才算抽烟）。

    - visible:     画面是否检出香烟（诊断用）
    - in_mouth:    香烟框中心落入嘴部外扩区 → 在嘴里
    - in_hand:     香烟紧挨一只"近嘴的手" → 在手上（被送入嘴边）
    """

    visible: bool = False
    in_mouth: bool = False
    in_hand: bool = False

    @property
    def position_locked(self) -> bool:
        """香烟是否锁定在「手/嘴」位置（放桌上/画面其他位置 = 不算）。"""
        return self.in_mouth or self.in_hand


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _box_center(box: Box) -> tuple[float, float]:
    return (box.x1 + box.x2) / 2.0, (box.y1 + box.y2) / 2.0


def evaluate_cigarette(
    cig_boxes: list[Box] | None, pose: PoseFeatures, config: SmokingConfig
) -> CigaretteSignal:
    """判定香烟是否「在嘴里」或「在手上」；都不是则视为画面里但未抽（桌上香烟）。

    放宽判据以适应用户规则（烟在手上/嘴里 = 抽烟）：
    - 在嘴里：烟框与嘴部框重叠，或框中心落入放大的嘴部区（容忍烟伸出嘴边/框偏大）
    - 在手上：烟框中心靠近任意检测到手的关键点（不再强求"手必须近嘴"，
      避免 MediaPipe 手势因角度/遮挡判不到而误阻断）
    """
    if not cig_boxes:
        return CigaretteSignal(visible=False)
    visible = True
    in_mouth = False
    in_hand = False
    if pose.mouth_box is not None:
        region = pose.mouth_box.expand(config.mouth_region_expand * 1.6)
        mouth_size = max(pose.mouth_box.width, pose.mouth_box.height)
        for b in cig_boxes:
            if _box_overlaps(b, pose.mouth_box) or region.contains(*_box_center(b)):
                in_mouth = True
                break
        for hand in pose.hands:
            hand_pts = (hand.wrist, hand.index_tip, hand.thumb_tip, hand.middle_tip)
            for b in cig_boxes:
                if any(
                    _distance(_box_center(b), p) < mouth_size * config.cig_in_hand_proximity
                    for p in hand_pts
                ):
                    in_hand = True
                    break
            if in_hand:
                break
    elif pose.hands:
        # 无嘴部（无脸）时仍可判"在手上"；用固定基准尺估距离
        for hand in pose.hands:
            hand_pts = (hand.wrist, hand.index_tip, hand.thumb_tip, hand.middle_tip)
            for b in cig_boxes:
                if any(_distance(_box_center(b), p) < 80.0 for p in hand_pts):
                    in_hand = True
                    break
            if in_hand:
                break
    return CigaretteSignal(visible=visible, in_mouth=in_mouth, in_hand=in_hand)


def _box_overlaps(a: Box, b: Box) -> bool:
    """两个框是否相交。"""
    return not (a.x2 < b.x1 or b.x2 < a.x1 or a.y2 < b.y1 or b.y2 < a.y1)


def evaluate_frame(pose: PoseFeatures, config: SmokingConfig) -> SmokingSignal:
    """评估单帧是否呈现夹烟手势（食指近嘴 + 指尖聚拢 + 手腕入区）。

    未命中时也返回最接近命中的那只手的细节，供监控面板诊断。
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
    """宽松版手-嘴判定（监控 Overlay 距离标注用，非检测判据）。"""
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
        # 香烟独立通道：滚动窗口内的"位置锁定"检出时刻序列（在嘴/在手才算）
        self._cig_times: list[float] = []
        # 香烟"在嘴里"的强证据时刻序列（无需手势即确认）
        self._mouth_times: list[float] = []
        # 手势佐证：窗口内食指近嘴的时刻序列（独立通道防误检用）
        self._gesture_times: list[float] = []
        # 行为分类确认：窗口内分类为 smoking 的时刻序列（抑制香烟误检）
        self._cls_times: list[float] = []

    @property
    def state(self) -> SmokingState:
        return self._state

    def monitor_info(self, timestamp: float) -> dict[str, object]:
        """状态机内部快照（监控中心诊断用）。"""
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
            "mouth_hits_recent": len(self._mouth_times),
            "gesture_frames_recent": len(self._gesture_times),
            "classification_frames_recent": len(self._cls_times),
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
        self._mouth_times = []
        self._gesture_times = []
        self._cls_times = []

    def update(
        self,
        signal: SmokingSignal,
        timestamp: float,
        cigarette_visible: bool = False,
        smoking_cls: str | None = None,
        smoking_cls_conf: float = 0.0,
        cig: CigaretteSignal | None = None,
    ) -> list[Event]:
        events: list[Event] = []
        if cig is None:
            # 向后兼容：未传位置信号时，仅当检出香烟才视为"位置锁定(在手上送嘴)"
            cig = CigaretteSignal(
                visible=cigarette_visible, in_mouth=False, in_hand=cigarette_visible
            )
        if cig.position_locked:
            self._last_cigarette_seen = timestamp
            self._cig_times.append(timestamp)
        if cig.in_mouth:
            self._mouth_times.append(timestamp)
        window = self._config.cigarette_confirm_window_seconds
        while self._cig_times and timestamp - self._cig_times[0] > window:
            self._cig_times.pop(0)
        while self._mouth_times and timestamp - self._mouth_times[0] > window:
            self._mouth_times.pop(0)
        if signal.index_near:
            self._gesture_times.append(timestamp)
        while self._gesture_times and timestamp - self._gesture_times[0] > window:
            self._gesture_times.pop(0)
        if smoking_cls == "smoking" and smoking_cls_conf >= self._config.classifier_min_conf:
            self._cls_times.append(timestamp)
        while self._cls_times and timestamp - self._cls_times[0] > window:
            self._cls_times.pop(0)

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

        # 香烟"在嘴里"强确认：窗口内香烟框落入嘴部区达阈即确认（无需手势，抽烟最直接证据）
        if (
            self._state is not SmokingState.SMOKING
            and len(self._mouth_times) >= self._config.cig_in_mouth_confirm_frames
        ):
            self._state = SmokingState.SMOKING
            if self._session_start <= 0.0:
                self._session_start = self._mouth_times[0]
            self._last_hit = timestamp
            events.append(
                SmokingStarted(device_id=self._device_id, occurred_at=_to_datetime(timestamp))
            )
            return events

        # 香烟独立通道：窗口内"位置锁定"(在嘴/在手)检出达标即确认。
        # 香烟位置已由 evaluate_cigarette 限定为烟在嘴/手旁，桌上烟不会 position_locked，
        # 故不再要求额外的"手近嘴"手势佐证（那会误挡"手拿烟在胸前"的真实抽烟）。
        if (
            cig.position_locked
            and self._state is not SmokingState.SMOKING
            and len(self._cig_times) >= self._config.cigarette_confirm_frames
            and timestamp - self._cig_times[0] >= self._config.cigarette_min_seconds
            and self._classifier_gate_ok()
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

    def _classifier_gate_ok(self) -> bool:
        """行为分类确认闸门：开启时要求窗口内分类为 smoking 的帧数达标。

        关闭（classifier_confirm_frames<=0）时恒通过，不影响原逻辑；
        开启时需 smoking-cls 在窗口内至少投出 classifier_confirm_frames 次"smoking"票，
        以减少"笔/手表/五官被误检为香烟"造成的虚警。
        """
        n = self._config.classifier_confirm_frames
        if n <= 0:
            return True
        return len(self._cls_times) >= n

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
