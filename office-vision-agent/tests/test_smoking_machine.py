"""抽烟会话状态机测试（手势形态 + 往返运动模式）。"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from plugins.smoking.detector import (
    CigaretteSignal,
    SmokingConfig,
    SmokingSessionMachine,
    SmokingSignal,
    SmokingState,
    evaluate_cigarette,
    evaluate_frame,
    hand_near_mouth,
)

from agent.events.types import SmokingEnded, SmokingStarted
from agent.vision.frame import Box, HandFeatures, PoseFeatures

BASE = 1000.0


def _config(**overrides: object) -> SmokingConfig:
    kwargs: dict[str, object] = {
        "min_hits_to_start": 4,
        "min_suspect_seconds": 0.0,
        "min_round_trips": 0,
        "no_detection_timeout": 30.0,
        "min_duration": 5.0,
    }
    kwargs.update(overrides)
    return SmokingConfig(**kwargs)  # type: ignore[arg-type]


def _make_machine(**overrides: object) -> SmokingSessionMachine:
    return SmokingSessionMachine(_config(**overrides), device_id="dev-1")


def _feed_hits(
    machine: SmokingSessionMachine, count: int, start: float = BASE, step: float = 1.0
) -> list[object]:
    events: list[object] = []
    for i in range(count):
        events.extend(machine.update(SmokingSignal(hit=True), start + i * step))
    return events


def _hit(wrist_y: float) -> SmokingSignal:
    return SmokingSignal(hit=True, index_near=True, grip=True, wrist_y=wrist_y)


def _feed_motion(machine: SmokingSessionMachine, ys: Sequence[float]) -> list[object]:
    """按 0.5s 间隔喂入手腕 y 序列（y 越小越靠上）。"""
    events: list[object] = []
    for i, y in enumerate(ys):
        events.extend(machine.update(_hit(y), BASE + i * 0.5))
    return events


class TestFrameHeuristic:
    def test_食指近嘴且聚拢_命中(self) -> None:
        mouth = Box(100, 100, 140, 130)
        hand = HandFeatures(
            wrist=(110, 120), thumb_tip=(108, 108), index_tip=(112, 110), middle_tip=(0, 0)
        )
        signal = evaluate_frame(PoseFeatures(mouth_box=mouth, hands=[hand]), _config())
        assert signal.hit is True
        assert signal.wrist_y == 120

    def test_指尖分开_托手姿势_不命中(self) -> None:
        mouth = Box(100, 100, 140, 130)
        hand = HandFeatures(
            wrist=(110, 120), thumb_tip=(60, 200), index_tip=(112, 110), middle_tip=(200, 50)
        )
        signal = evaluate_frame(PoseFeatures(mouth_box=mouth, hands=[hand]), _config())
        assert signal.hit is False
        assert signal.index_near is True
        assert signal.grip is False

    def test_手腕远离嘴部_不命中(self) -> None:
        mouth = Box(100, 100, 140, 130)
        hand = HandFeatures(
            wrist=(500, 500), thumb_tip=(108, 108), index_tip=(112, 110), middle_tip=(0, 0)
        )
        assert evaluate_frame(PoseFeatures(mouth_box=mouth, hands=[hand]), _config()).hit is False

    def test_无脸或无手_不命中(self) -> None:
        assert evaluate_frame(PoseFeatures(), _config()).hit is False

    def test_hand_near_mouth_仍供overlay使用(self) -> None:
        mouth = Box(100, 100, 140, 130)
        hand = HandFeatures(
            wrist=(50, 200), thumb_tip=(110, 110), index_tip=(0, 0), middle_tip=(0, 0)
        )
        assert hand_near_mouth(PoseFeatures(mouth_box=mouth, hands=[hand]), 1.8) is True


class TestStateMachine:
    def test_命中数与时长达标_发SmokingStarted(self) -> None:
        machine = _make_machine(min_hits_to_start=4)
        events = _feed_hits(machine, 4)
        assert [type(e) for e in events] == [SmokingStarted]
        assert machine.state is SmokingState.SMOKING

    def test_未达阈值不发事件(self) -> None:
        machine = _make_machine(min_hits_to_start=4)
        events = _feed_hits(machine, 3)
        assert events == []
        assert machine.state is SmokingState.SUSPECT

    def test_命中数达标但时长不足_不确认(self) -> None:
        machine = _make_machine(min_hits_to_start=4, min_suspect_seconds=3.0)
        events = _feed_hits(machine, 10, step=0.1)  # 总时长仅 0.9s
        assert events == []
        assert machine.state is SmokingState.SUSPECT

    def test_静态手放嘴上_无往返_不确认(self) -> None:
        machine = _make_machine(min_hits_to_start=4, min_round_trips=1)
        events = _feed_motion(machine, [300.0] * 30)  # 手腕始终停在同一高度
        assert events == []
        assert machine.state is SmokingState.SUSPECT

    def test_有往返运动_确认抽烟(self) -> None:
        machine = _make_machine(min_hits_to_start=4, min_round_trips=1)
        ys = [320, 300, 200, 150, 200, 300, 320] + [320] * 5
        events = _feed_motion(machine, ys)
        assert [type(e) for e in events] == [SmokingStarted]
        assert machine.state is SmokingState.SMOKING

    def test_suspect连续丢失_回到idle(self) -> None:
        machine = _make_machine(min_hits_to_start=4, max_misses_suspect=2)
        _feed_hits(machine, 2)
        for i in range(3):
            machine.update(SmokingSignal(hit=False), BASE + 10 + i)
        assert machine.state is SmokingState.IDLE

    def test_超时收尾_发SmokingEnded带时长(self) -> None:
        machine = _make_machine(min_hits_to_start=4, no_detection_timeout=30.0)
        _feed_hits(machine, 4)  # t=1000..1003
        events = machine.update(SmokingSignal(hit=False), BASE + 40.0)  # 距最后命中 37s > 30s
        assert len(events) == 1
        ended = events[0]
        assert isinstance(ended, SmokingEnded)
        assert ended.duration_seconds == pytest.approx(40.0)
        assert machine.state is SmokingState.IDLE

    def test_过短会话丢弃(self) -> None:
        machine = _make_machine(min_hits_to_start=2, min_duration=50.0, no_detection_timeout=5.0)
        _feed_hits(machine, 2)  # 会话起于 t=1000，最后命中 t=1001
        events = machine.update(SmokingSignal(hit=False), BASE + 7.0)  # 时长 7s < 50s → 丢弃
        assert events == []
        assert machine.state is SmokingState.IDLE

    def test_一根烟只一条记录(self) -> None:
        machine = _make_machine(min_hits_to_start=4, no_detection_timeout=30.0)
        _feed_hits(machine, 10)  # 持续命中
        events = machine.update(SmokingSignal(hit=False), BASE + 50.0)
        assert [type(e) for e in events] == [SmokingEnded]
        events_after = machine.update(SmokingSignal(hit=False), BASE + 90.0)
        assert events_after == []

    def test_reset_清空状态(self) -> None:
        machine = _make_machine(min_hits_to_start=4)
        _feed_hits(machine, 4)
        machine.reset()
        assert machine.state is SmokingState.IDLE
        assert _feed_hits(machine, 3) == []


class TestCigaretteFusion:
    """香烟检出融合：独立通道窗口内达标 + 最低手势佐证即确认；手势通道有证据时放宽阈值。"""

    def test_窗口内检出达标_有手势佐证_确认(self) -> None:
        machine = _make_machine()
        events: list[object] = []
        for i in range(3):  # 3 次检出跨 1s，食指近嘴仅一帧（最低佐证）
            signal = SmokingSignal(hit=False, index_near=(i == 1))
            events.extend(machine.update(signal, BASE + i * 0.5, cigarette_visible=True))
        assert [type(e) for e in events] == [SmokingStarted]
        assert machine.state is SmokingState.SMOKING

    def test_持续检出但无手势佐证_不确认(self) -> None:
        """笔/手表/五官误检场景：香烟持续高置信度检出但手不在嘴旁 → 阻断。"""
        machine = _make_machine()
        events: list[object] = []
        for i in range(20):  # 远超确认门槛的持续检出，手势全程无佐证
            events.extend(
                machine.update(SmokingSignal(hit=False), BASE + i * 0.5, cigarette_visible=True)
            )
        assert events == []
        assert machine.state is SmokingState.IDLE

    def test_手势佐证超出窗口_不计入(self) -> None:
        machine = _make_machine(cigarette_confirm_window_seconds=3.0)
        # 早期一帧食指近嘴，间隔 5s 后才持续检出 → 佐证已过期，不确认
        machine.update(SmokingSignal(hit=False, index_near=True), BASE)
        events: list[object] = []
        for i in range(3):
            events.extend(
                machine.update(
                    SmokingSignal(hit=False), BASE + 5.0 + i * 0.5, cigarette_visible=True
                )
            )
        assert events == []
        assert machine.state is SmokingState.IDLE

    def test_检出次数不足_不确认(self) -> None:
        machine = _make_machine()
        events: list[object] = []
        for i in range(2):
            events.extend(
                machine.update(SmokingSignal(hit=False), BASE + i * 0.5, cigarette_visible=True)
            )
        assert events == []
        assert machine.state is SmokingState.IDLE

    def test_帧间闪烁_窗口内计数不中断(self) -> None:
        machine = _make_machine(cigarette_confirm_window_seconds=3.0)
        events: list[object] = []
        # 检出-漏检-检出-检出，漏检不清空窗口计数；首帧提供手势佐证
        seq = [True, False, True, True]
        for i, visible in enumerate(seq):
            signal = SmokingSignal(hit=False, index_near=(i == 0))
            events.extend(machine.update(signal, BASE + i * 0.5, cigarette_visible=visible))
        assert [type(e) for e in events] == [SmokingStarted]

    def test_检出间隔超出窗口_重新计数(self) -> None:
        machine = _make_machine(cigarette_confirm_window_seconds=3.0, cigarette_confirm_frames=2)
        machine.update(SmokingSignal(hit=False), BASE, cigarette_visible=True)
        events: list[object] = []
        # 间隔 5s 超出窗口，第二次检出仅算 1 次，不足确认门槛
        events.extend(machine.update(SmokingSignal(hit=False), BASE + 5.0, cigarette_visible=True))
        assert events == []
        assert machine.state is SmokingState.IDLE

    def test_观察时长不足_不确认(self) -> None:
        machine = _make_machine(cigarette_min_seconds=2.0)
        events: list[object] = []
        for i in range(3):  # 3 次检出仅跨 0.2s < 2s
            events.extend(
                machine.update(SmokingSignal(hit=False), BASE + i * 0.1, cigarette_visible=True)
            )
        assert events == []
        assert machine.state is SmokingState.IDLE

    def test_香烟确认后续_香烟证据延续会话(self) -> None:
        machine = _make_machine(no_detection_timeout=10.0)
        for i in range(3):
            signal = SmokingSignal(hit=False, index_near=(i == 0))
            machine.update(signal, BASE + i * 0.5, cigarette_visible=True)
        assert machine.state is SmokingState.SMOKING
        # 手势全程无命中，但香烟持续检出 → 超时收尾不触发
        events = machine.update(SmokingSignal(hit=False), BASE + 20.0, cigarette_visible=True)
        assert events == []
        assert machine.state is SmokingState.SMOKING

    def test_检出香烟_低命中数即确认(self) -> None:
        machine = _make_machine(
            min_hits_to_start=4,
            cigarette_min_hits_to_start=2,
            cigarette_min_suspect_seconds=0.0,
        )
        events: list[object] = []
        for i in range(2):
            events.extend(machine.update(SmokingSignal(hit=True), BASE + i, cigarette_visible=True))
        assert [type(e) for e in events] == [SmokingStarted]

    def test_无香烟检出_同样命中数不确认(self) -> None:
        machine = _make_machine(min_hits_to_start=4, cigarette_min_hits_to_start=2)
        events = _feed_hits(machine, 2)  # 严格阈值 4，仅 2 次命中
        assert events == []
        assert machine.state is SmokingState.SUSPECT

    def test_香烟证据过期_回退严格阈值(self) -> None:
        machine = _make_machine(
            min_hits_to_start=4,
            cigarette_min_hits_to_start=2,
            cigarette_min_suspect_seconds=0.0,
            cigarette_memory_seconds=2.0,
        )
        # 首帧检出香烟，之后 4 帧未再检出且时间已超出记忆窗口
        machine.update(SmokingSignal(hit=True), BASE, cigarette_visible=True)
        events: list[object] = []
        for i in range(1, 3):
            events.extend(machine.update(SmokingSignal(hit=True), BASE + 5.0 + i))
        assert events == []  # 证据已过期，2 次命中不足严格阈值 4
        assert machine.state is SmokingState.SUSPECT

    def test_有香烟无往返_独立通道仍确认(self) -> None:
        """手势往返未达标，但香烟窗口内检出达标 → 直接确认（手势不阻断强证据）。"""
        machine = _make_machine(
            min_hits_to_start=4,
            min_round_trips=1,
            cigarette_min_hits_to_start=2,
            cigarette_min_suspect_seconds=0.0,
        )
        events: list[object] = []
        for i in range(6):  # 手腕静止同一高度，无往返
            events.extend(machine.update(_hit(300.0), BASE + i * 0.5, cigarette_visible=True))
        assert [type(e) for e in events] == [SmokingStarted]
        assert machine.state is SmokingState.SMOKING


class TestClassifierGate:
    """行为分类确认通道：开启后香烟通道需额外满足 smoking-cls 投票，降低误检。"""

    def test_分类器未开启_不影响原通道(self) -> None:
        machine = _make_machine(classifier_confirm_frames=0)
        events: list[object] = []
        for i in range(3):
            signal = SmokingSignal(hit=False, index_near=(i == 0))
            events.extend(machine.update(signal, BASE + i * 0.5, cigarette_visible=True))
        assert [type(e) for e in events] == [SmokingStarted]

    def test_开启_无smoking票_不确认(self) -> None:
        """笔/手表误检场景：香烟+手势齐备，但整帧分类不是 smoking → 阻断。"""
        machine = _make_machine(classifier_confirm_frames=1)
        events: list[object] = []
        for i in range(3):
            signal = SmokingSignal(hit=False, index_near=(i == 0))
            events.extend(
                machine.update(
                    signal, BASE + i * 0.5, cigarette_visible=True, smoking_cls="normal", smoking_cls_conf=0.9
                )
            )
        assert events == []
        assert machine.state is SmokingState.IDLE

    def test_开启_有smoking票_确认(self) -> None:
        machine = _make_machine(classifier_confirm_frames=1)
        events: list[object] = []
        for i in range(3):
            signal = SmokingSignal(hit=False, index_near=(i == 0))
            events.extend(
                machine.update(
                    signal, BASE + i * 0.5, cigarette_visible=True, smoking_cls="smoking", smoking_cls_conf=0.9
                )
            )
        assert [type(e) for e in events] == [SmokingStarted]
        assert machine.state is SmokingState.SMOKING

    def test_smoking票不足_不确认(self) -> None:
        machine = _make_machine(classifier_confirm_frames=2)
        events: list[object] = []
        for i in range(3):
            signal = SmokingSignal(hit=False, index_near=(i == 0))
            events.extend(
                machine.update(
                    signal,
                    BASE + i * 0.5,
                    cigarette_visible=True,
                    smoking_cls="smoking" if i == 0 else "normal",
                    smoking_cls_conf=0.9,
                )
            )
        assert events == []
        assert machine.state is SmokingState.IDLE

    def test_分类置信度不足_不计票(self) -> None:
        machine = _make_machine(classifier_confirm_frames=1, classifier_min_conf=0.6)
        events: list[object] = []
        for i in range(3):
            signal = SmokingSignal(hit=False, index_near=(i == 0))
            events.extend(
                machine.update(
                    signal, BASE + i * 0.5, cigarette_visible=True, smoking_cls="smoking", smoking_cls_conf=0.3
                )
            )
        assert events == []
        assert machine.state is SmokingState.IDLE


class TestCigarettePosition:
    """用户规则：香烟在手里或嘴里才算抽烟；放桌上（不锁位置）不算。"""

    @staticmethod
    def _in_mouth() -> CigaretteSignal:
        return CigaretteSignal(visible=True, in_mouth=True)

    @staticmethod
    def _in_hand() -> CigaretteSignal:
        return CigaretteSignal(visible=True, in_hand=True)

    def test_香烟在嘴里_无需手势_确认(self) -> None:
        """烟在嘴里是抽烟最直接证据：窗口内达阈即使无手势也确认。"""
        machine = _make_machine(cig_in_mouth_confirm_frames=2)
        events: list[object] = []
        for i in range(2):
            events.extend(
                machine.update(SmokingSignal(hit=False), BASE + i * 0.5, cig=self._in_mouth())
            )
        assert [type(e) for e in events] == [SmokingStarted]
        assert machine.state is SmokingState.SMOKING

    def test_香烟在手上且手近嘴_确认(self) -> None:
        """烟在手+手近嘴（夹烟送嘴）：位置锁定检出达标 + 手势佐证 → 确认。"""
        machine = _make_machine()
        events: list[object] = []
        for i in range(3):
            signal = SmokingSignal(hit=False, index_near=(i == 0))
            events.extend(machine.update(signal, BASE + i * 0.5, cig=self._in_hand()))
        assert [type(e) for e in events] == [SmokingStarted]

    def test_香烟放桌上_不锁位置_不确认(self) -> None:
        """用户规则：香烟出现在画面（桌上）但不在手/嘴 → 绝不确认抽烟。"""
        machine = _make_machine(cig_in_mouth_confirm_frames=2)
        events: list[object] = []
        desk = CigaretteSignal(visible=True, in_mouth=False, in_hand=False)  # 位置未锁定
        for i in range(20):
            signal = SmokingSignal(hit=False, index_near=(i == 0))
            events.extend(machine.update(signal, BASE + i * 0.5, cig=desk))
        assert events == []
        assert machine.state is SmokingState.IDLE

    def test_evaluate_cigarette_框在嘴里_锁定位(self) -> None:
        mouth = Box(100, 100, 140, 130)
        cig_box = Box(115, 108, 128, 120)  # 中心(121.5,114) 在嘴部内
        sig = evaluate_cigarette([cig_box], PoseFeatures(mouth_box=mouth), _config())
        assert sig.in_mouth is True and sig.position_locked is True

    def test_evaluate_cigarette_桌上_不锁定位(self) -> None:
        mouth = Box(100, 100, 140, 130)
        hand = HandFeatures(
            wrist=(110, 120), thumb_tip=(108, 108), index_tip=(112, 110), middle_tip=(0, 0)
        )
        cig_box = Box(400, 500, 420, 520)  # 远离嘴和手 → 桌上
        sig = evaluate_cigarette(
            [cig_box], PoseFeatures(mouth_box=mouth, hands=[hand]), _config()
        )
        assert sig.visible is True and sig.in_mouth is False and sig.in_hand is False
        assert sig.position_locked is False
