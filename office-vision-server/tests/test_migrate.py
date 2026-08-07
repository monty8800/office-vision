"""迁移测试：旧表 smoking_records → behavior_sessions（自动、幂等）。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from server.main import create_app


def _make_legacy_db(path: Path) -> None:
    """构造只含旧抽烟表的遗留数据库（模拟升级前的线上文件）。"""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE smoking_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id VARCHAR(64) NOT NULL,
            start_time DATETIME NOT NULL,
            end_time DATETIME NOT NULL,
            duration_seconds FLOAT NOT NULL,
            created_at DATETIME NOT NULL,
            UNIQUE (device_id, start_time)
        )
        """
    )
    conn.execute(
        "INSERT INTO smoking_records"
        " (device_id, start_time, end_time, duration_seconds, created_at)"
        " VALUES ('mac-main', '2026-08-06 01:00:00.000000',"
        " '2026-08-06 01:05:00.000000', 300.0, '2026-08-06 01:05:00.000000')"
    )
    conn.commit()
    conn.close()


def test_遗留抽烟数据自动迁移(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    _make_legacy_db(db_path)
    app = create_app(f"sqlite+aiosqlite:///{db_path}")

    with TestClient(app) as client:  # lifespan 触发迁移
        items = client.get("/api/behaviors/smoking/sessions").json()["items"]
        assert len(items) == 1
        assert items[0]["duration_seconds"] == 300.0
        assert items[0]["start_time"] == "2026-08-06T01:00:00+00:00"

    with TestClient(app) as client:  # 二次启动幂等，不产生重复
        items = client.get("/api/behaviors/smoking/sessions").json()["items"]
        assert len(items) == 1
