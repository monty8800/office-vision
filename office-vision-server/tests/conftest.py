"""Server 测试公共夹具：SQLite 临时库 + 完整 FastAPI 应用。"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from server.main import create_app


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    with TestClient(app) as test_client:  # 触发 lifespan 建库
        yield test_client


def make_event(
    event_type: str,
    device_id: str = "mac-main",
    event_id: str | None = None,
    payload: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    return {
        "event_id": event_id or f"evt-{event_type}-{datetime.now(UTC).timestamp()}",
        "device_id": device_id,
        "event_type": event_type,
        "occurred_at": (occurred_at or datetime.now(UTC)).isoformat(),
        "payload": payload or {},
    }


def smoking_ended_payload(start: datetime, end: datetime, duration: float) -> dict[str, Any]:
    return {
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "duration_seconds": duration,
    }
