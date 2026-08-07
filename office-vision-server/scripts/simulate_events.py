"""开发演示：向 Server 注入模拟事件（Dashboard 展示用，非生产功能）。

用法：
    uv run python scripts/simulate_events.py [--url http://localhost:8000]
"""

from __future__ import annotations

import argparse
import json
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta


def make_event(event_type: str, occurred_at: datetime, payload: dict | None = None) -> dict:
    return {
        "event_id": uuid.uuid4().hex,
        "device_id": "mac-main",
        "event_type": event_type,
        "occurred_at": occurred_at.isoformat(),
        "payload": payload or {},
    }


def smoking_session(start: datetime, duration_seconds: float) -> list[dict]:
    end = start + timedelta(seconds=duration_seconds)
    payload = {
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "duration_seconds": duration_seconds,
    }
    return [
        make_event("SmokingStarted", start),
        make_event("SmokingEnded", end, payload),
    ]


def build_events(now: datetime) -> list[dict]:
    events: list[dict] = []
    # 过去 6 天每天 1~3 次（趋势图）
    for days_ago in range(6, 0, -1):
        day = now - timedelta(days=days_ago)
        for i in range((days_ago % 3) + 1):
            events += smoking_session(day.replace(hour=10 + i * 2, minute=15), 90 + i * 40)
    # 今天：上午两次
    events += smoking_session(now.replace(hour=9, minute=40, second=0), 150)
    events += smoking_session(now.replace(hour=11, minute=5, second=0), 210)
    # Presence 时间线：上班 → 短暂离开 → 回来
    events.append(make_event("SeatOccupied", now.replace(hour=9, minute=0, second=0)))
    events.append(make_event("SeatEmpty", now - timedelta(minutes=20)))
    events.append(make_event("SeatOccupied", now - timedelta(minutes=15)))
    events.sort(key=lambda e: e["occurred_at"])
    return events


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()

    events = build_events(datetime.now(UTC))
    request = urllib.request.Request(
        f"{args.url}/api/events",
        data=json.dumps({"events": events}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:  # noqa: S310
        print(response.status, response.read().decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
