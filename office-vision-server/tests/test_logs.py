"""客户端日志 API 测试：接收幂等 → 列表/详情查询 → 保留期清理。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from server.core.config import LogsSection, ServerConfig
from server.main import create_app


def make_chunk(
    chunk_id: str = "c1",
    device_id: str = "mac-main",
    content: str = "line-1\nline-2\n",
    trigger: str = "periodic",
) -> dict[str, str]:
    return {
        "chunk_id": chunk_id,
        "device_id": device_id,
        "component": "agent",
        "trigger": trigger,
        "logged_at": datetime.now(UTC).isoformat(),
        "content": content,
    }


class TestLogIngest:
    def test_接收并查询(self, client: TestClient) -> None:
        response = client.post("/api/logs", json=make_chunk(content="hello\n"))
        assert response.status_code == 200
        assert response.json() == {"accepted": 1, "duplicates": 0}

        listing = client.get("/api/logs").json()
        assert listing["total"] == 1
        chunk = listing["chunks"][0]
        assert chunk["device_id"] == "mac-main"
        assert chunk["trigger"] == "periodic"
        assert chunk["size"] == len(b"hello\n")
        assert "content" not in chunk  # 列表不含内容

        detail = client.get(f"/api/logs/{chunk['chunk_id']}").json()
        assert detail["content"] == "hello\n"

    def test_chunk幂等(self, client: TestClient) -> None:
        chunk = make_chunk(chunk_id="dup-1")
        client.post("/api/logs", json=chunk)
        response = client.post("/api/logs", json=chunk)
        assert response.json() == {"accepted": 0, "duplicates": 1}
        assert client.get("/api/logs").json()["total"] == 1

    def test_设备过滤(self, client: TestClient) -> None:
        client.post("/api/logs", json=make_chunk(chunk_id="c1", device_id="dev-a"))
        client.post("/api/logs", json=make_chunk(chunk_id="c2", device_id="dev-b"))
        result = client.get("/api/logs", params={"device_id": "dev-a"}).json()
        assert result["total"] == 1
        assert result["chunks"][0]["device_id"] == "dev-a"

    def test_超大chunk拒绝(self, client: TestClient) -> None:
        chunk = make_chunk(chunk_id="big", content="x" * (1024 * 1024 + 1))
        response = client.post("/api/logs", json=chunk)
        assert response.status_code == 413

    def test_详情不存在返回404(self, client: TestClient) -> None:
        assert client.get("/api/logs/not-exist").status_code == 404


class TestRetention:
    def test_超期记录自动清理(self, tmp_path: Path) -> None:
        # retention_days=0：cutoff=now，入库后顺带清理即删除（验证清理链路）
        config = ServerConfig(logs=LogsSection(retention_days=0))
        app = create_app(f"sqlite+aiosqlite:///{tmp_path / 'logs.db'}", config=config)
        with TestClient(app) as test_client:
            test_client.post("/api/logs", json=make_chunk(chunk_id="c1"))
            assert test_client.get("/api/logs").json()["total"] == 0

    def test_保留期内不清理(self, client: TestClient) -> None:
        # 默认 retention_days=14，新入库记录不受影响
        client.post("/api/logs", json=make_chunk(chunk_id="c1"))
        assert client.get("/api/logs").json()["total"] == 1
