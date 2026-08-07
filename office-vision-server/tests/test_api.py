"""Server API 端到端测试：事件接收 → 幂等 → 行为会话生成 → 统计查询。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from tests.conftest import make_event, smoking_ended_payload


class TestEventIngest:
    def test_health(self, client: TestClient) -> None:
        assert client.get("/api/health").json() == {"status": "ok"}

    def test_批量接收事件(self, client: TestClient) -> None:
        response = client.post(
            "/api/events",
            json={
                "events": [
                    make_event("SeatOccupied", event_id="e1"),
                    make_event("SeatEmpty", event_id="e2"),
                ]
            },
        )
        assert response.status_code == 200
        assert response.json() == {"accepted": 2, "duplicates": 0}

    def test_幂等去重(self, client: TestClient) -> None:
        event = make_event("SeatOccupied", event_id="dup-1")
        client.post("/api/events", json={"events": [event]})
        response = client.post("/api/events", json={"events": [event]})
        assert response.json() == {"accepted": 0, "duplicates": 1}

    def test_事件流水查询(self, client: TestClient) -> None:
        client.post("/api/events", json={"events": [make_event("SeatOccupied", event_id="e1")]})
        events = client.get("/api/events").json()["events"]
        assert len(events) == 1
        assert events[0]["event_type"] == "SeatOccupied"

    def test_心跳与在线状态(self, client: TestClient) -> None:
        client.post("/api/events", json={"events": [make_event("SeatOccupied", event_id="e1")]})
        agents = client.get("/api/agents").json()["agents"]
        assert agents[0]["device_id"] == "mac-main"
        assert agents[0]["online"] is True
        assert agents[0]["event_count"] == 1

    def test_AgentAlive心跳刷新在线判定(self, client: TestClient) -> None:
        """心跳与业务事件无关，仅证明进程存活，应正常刷新 last_seen。"""
        client.post(
            "/api/events", json={"events": [make_event("AgentAlive", event_id="hb-1")]}
        )
        agents = client.get("/api/agents").json()["agents"]
        assert agents[0]["device_id"] == "mac-main"
        assert agents[0]["online"] is True


class TestTimezone:
    """时间统一语义：入库归一 UTC，输出带时区标记供前端转本地。"""

    def test_带时区UTC时间_原样输出带标记(self, client: TestClient) -> None:
        moment = datetime.now(UTC)
        client.post(
            "/api/events",
            json={"events": [make_event("SeatOccupied", event_id="tz1", occurred_at=moment)]},
        )
        out = client.get("/api/events").json()["events"][0]["occurred_at"]
        assert datetime.fromisoformat(out) == moment

    def test_naive本地时间_归一为UTC(self, client: TestClient) -> None:
        local_now = datetime.now().astimezone()
        naive_local = local_now.replace(tzinfo=None)
        client.post(
            "/api/events",
            json={"events": [make_event("SeatOccupied", event_id="tz2", occurred_at=naive_local)]},
        )
        out = client.get("/api/events").json()["events"][0]["occurred_at"]
        assert out.endswith("+00:00")
        assert datetime.fromisoformat(out) == local_now.astimezone(UTC)

    def test_抽烟记录时间输出带时区标记(self, client: TestClient) -> None:
        start = datetime.now(UTC) - timedelta(minutes=2)
        end = start + timedelta(seconds=60)
        client.post(
            "/api/events",
            json={
                "events": [
                    make_event(
                        "SmokingEnded",
                        event_id="tz3",
                        occurred_at=end,
                        payload=smoking_ended_payload(start, end, 60.0),
                    )
                ]
            },
        )
        item = client.get("/api/behaviors/smoking/sessions").json()["items"][0]
        assert item["start_time"].endswith("+00:00")
        assert datetime.fromisoformat(item["start_time"]) == start


class TestBehaviorStats:
    def _send_smoking_session(
        self, client: TestClient, start: datetime, duration: float, event_id: str
    ) -> None:
        end = start + timedelta(seconds=duration)
        client.post(
            "/api/events",
            json={
                "events": [
                    make_event(
                        "SmokingEnded",
                        event_id=event_id,
                        occurred_at=end,
                        payload=smoking_ended_payload(start, end, duration),
                    )
                ]
            },
        )

    def test_生成抽烟记录(self, client: TestClient) -> None:
        start = datetime.now(UTC) - timedelta(minutes=2)
        self._send_smoking_session(client, start, 120.0, "s1")
        records = client.get("/api/behaviors/smoking/sessions").json()
        assert len(records["items"]) == 1
        assert records["items"][0]["duration_seconds"] == 120.0

    def test_重复上报不产生重复记录(self, client: TestClient) -> None:
        start = datetime.now(UTC) - timedelta(minutes=2)
        self._send_smoking_session(client, start, 120.0, "s1")
        self._send_smoking_session(client, start, 120.0, "s1")  # 网络重试
        records = client.get("/api/behaviors/smoking/sessions").json()
        assert len(records["items"]) == 1

    def test_行为清单(self, client: TestClient) -> None:
        behaviors = client.get("/api/behaviors").json()["behaviors"]
        assert {"key": "smoking", "label": "抽烟"} in behaviors

    def test_未知行为返回404(self, client: TestClient) -> None:
        assert client.get("/api/behaviors/drinking/today").status_code == 404

    def test_今日统计含最近一次(self, client: TestClient) -> None:
        start = datetime.now(UTC) - timedelta(minutes=5)
        self._send_smoking_session(client, start, 100.0, "s1")
        self._send_smoking_session(client, start + timedelta(minutes=6), 200.0, "s2")
        summary = client.get("/api/behaviors/smoking/today").json()
        assert summary["count"] == 2
        assert summary["total_seconds"] == 300.0
        assert summary["avg_seconds"] == 150.0
        assert summary["last_duration_seconds"] == 200.0
        assert datetime.fromisoformat(summary["last_start_time"]) == start + timedelta(minutes=6)

    def test_无数据时最近一次为空(self, client: TestClient) -> None:
        summary = client.get("/api/behaviors/smoking/today").json()
        assert summary["count"] == 0
        assert summary["last_start_time"] is None

    def test_趋势补零(self, client: TestClient) -> None:
        start = datetime.now(UTC) - timedelta(minutes=1)
        self._send_smoking_session(client, start, 60.0, "s1")
        trend = client.get("/api/behaviors/smoking/trend?days=7").json()["days"]
        assert len(trend) == 7
        assert trend[-1]["count"] == 1  # 今天
        assert trend[-1]["total_seconds"] == 60.0
        assert trend[0]["count"] == 0  # 六天前补零

    def test_小时分布全天补零(self, client: TestClient) -> None:
        start = datetime.now(UTC) - timedelta(minutes=1)
        self._send_smoking_session(client, start, 60.0, "s1")
        hourly = client.get("/api/behaviors/smoking/hourly").json()
        assert len(hourly["hours"]) == 24  # 全天 0-23 时，不限制工作时间
        # 以事件自身的本地小时取桶，避免整点边界上"当前时刻"与"1分钟前"跨桶的抖动
        bucket = hourly["hours"][start.astimezone().hour]
        assert bucket["count"] == 1
        assert bucket["total_seconds"] == 60.0
        assert sum(h["count"] for h in hourly["hours"]) == 1


class TestPresence:
    def test_在岗状态推导(self, client: TestClient) -> None:
        now = datetime.now(UTC)
        client.post(
            "/api/events",
            json={
                "events": [
                    make_event(
                        "SeatOccupied", event_id="p1", occurred_at=now - timedelta(seconds=60)
                    ),
                    make_event("SeatEmpty", event_id="p2", occurred_at=now),
                ]
            },
        )
        devices = client.get("/api/presence").json()["devices"]
        assert devices["mac-main"]["state"] == "away"
