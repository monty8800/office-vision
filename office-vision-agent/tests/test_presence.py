"""PresenceManager 状态机测试。"""

from __future__ import annotations

from agent.events.types import PresenceResumed, PresenceSleeping, SeatEmpty, SeatOccupied
from agent.presence.manager import PresenceManager, PresenceSettings, PresenceState

DEVICE = "dev-1"
SETTINGS = PresenceSettings(sleep_after_seconds=300.0, resume_wait_seconds=3.0)


def _make() -> PresenceManager:
    return PresenceManager(DEVICE, SETTINGS)


class TestTransitions:
    def test_waiting_到人_发SeatOccupied(self) -> None:
        pm = _make()
        events = pm.update(person_present=True, timestamp=100.0)
        assert [type(e) for e in events] == [SeatOccupied]
        assert pm.state is PresenceState.WORKING

    def test_working_人离开画面_立即发SeatEmpty(self) -> None:
        pm = _make()
        pm.update(True, 100.0)
        events = pm.update(False, 105.0)
        assert [type(e) for e in events] == [SeatEmpty]
        assert pm.state is PresenceState.AWAY

    def test_away_人回来_发SeatOccupied(self) -> None:
        pm = _make()
        pm.update(True, 100.0)
        pm.update(False, 105.0)
        events = pm.update(True, 150.0)
        assert [type(e) for e in events] == [SeatOccupied]
        assert pm.state is PresenceState.WORKING

    def test_away超时_进入休眠_发PresenceSleeping(self) -> None:
        pm = _make()
        pm.update(True, 100.0)
        pm.update(False, 105.0)  # AWAY，最后见到人 t=100
        events = pm.update(False, 401.0)  # 100 + 300 + 1
        assert [type(e) for e in events] == [PresenceSleeping]
        assert pm.state is PresenceState.SLEEPING

    def test_waiting启动即无人超时_进入休眠(self) -> None:
        """启动后就没人：WAITING 无人超时也进入休眠（摄像头可关闭）。"""
        pm = _make()
        events = pm.update(False, 100.0)  # 启动即无人，entry_time=100
        assert events == []
        events = pm.update(False, 401.0)  # 100 + 300 + 1 无人超时
        assert [type(e) for e in events] == [PresenceSleeping]
        assert pm.state is PresenceState.SLEEPING

    def test_休眠中短暂出现不立即恢复(self) -> None:
        pm = _to_sleeping()
        events = pm.update(True, 500.0)
        assert events == []
        assert pm.state is PresenceState.SLEEPING

    def test_休眠中稳定出现_恢复_发PresenceResumed(self) -> None:
        pm = _to_sleeping()
        pm.update(True, 500.0)
        events = pm.update(True, 504.0)  # 稳定超过 resume_wait
        assert [type(e) for e in events] == [PresenceResumed]
        assert pm.state is PresenceState.WORKING

    def test_休眠中恢复失败_计时重置(self) -> None:
        pm = _to_sleeping()
        pm.update(True, 500.0)
        pm.update(False, 501.0)  # 中途消失
        pm.update(True, 502.0)  # 重新计时
        events = pm.update(True, 504.0)
        assert events == []
        assert pm.state is PresenceState.SLEEPING


class TestPipelineFlags:
    def test_working时运行完整管线(self) -> None:
        pm = _make()
        pm.update(True, 100.0)
        assert pm.run_full_pipeline is True

    def test_away时不运行完整管线(self) -> None:
        pm = _make()
        pm.update(True, 100.0)
        pm.update(False, 105.0)  # AWAY
        assert pm.run_full_pipeline is False

    def test_presence检测恒为True_休眠也要唤醒(self) -> None:
        pm = _to_sleeping()
        assert pm.run_presence_detection is True


def _to_sleeping() -> PresenceManager:
    pm = _make()
    pm.update(True, 100.0)
    pm.update(False, 105.0)
    pm.update(False, 401.0)
    assert pm.state is PresenceState.SLEEPING
    return pm
