"""LogUploader 测试：增量上传 / offset 持久化 / 轮转删除 / 行截断 / 错误防抖。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from agent.transport.log_uploader import LogUploader


class FakeServer:
    """MockTransport 包装：可控成功/失败，记录收到的 chunk。"""

    def __init__(self) -> None:
        self.ok = True
        self.chunks: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if not self.ok:
            return httpx.Response(500)
        self.chunks.append(json.loads(request.content))
        return httpx.Response(200, json={"accepted": 1, "duplicates": 0})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.MockTransport(self.handler), base_url="http://server"
        )


def make_uploader(
    tmp_path: Path, server: FakeServer, *, max_chunk_bytes: int = 262144
) -> LogUploader:
    log_dir = tmp_path / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return LogUploader(
        server_url="http://server",
        device_id="dev-1",
        log_file=log_dir / "agent.log",
        state_path=tmp_path / "data" / "log_upload_state.json",
        max_chunk_bytes=max_chunk_bytes,
        client=server.client(),
    )


def write_log(tmp_path: Path, text: str, name: str = "agent.log") -> Path:
    path = tmp_path / "data" / "logs" / name
    path.write_text(text, encoding="utf-8")
    return path


async def test_增量上传_offset持久化(tmp_path: Path) -> None:
    server = FakeServer()
    uploader = make_uploader(tmp_path, server)
    write_log(tmp_path, "line-1\nline-2\n")

    assert await uploader.flush_all() == 1
    assert server.chunks[0]["content"] == "line-1\nline-2\n"
    assert server.chunks[0]["device_id"] == "dev-1"
    assert server.chunks[0]["trigger"] == "periodic"

    # 无新增内容时不重复上传
    assert await uploader.flush_all() == 0

    # 追加内容后只上传增量
    with (tmp_path / "data" / "logs" / "agent.log").open("a", encoding="utf-8") as fh:
        fh.write("line-3\n")
    assert await uploader.flush_all() == 1
    assert server.chunks[-1]["content"] == "line-3\n"

    # offset 状态落盘，重建实例后不重传
    state = json.loads((tmp_path / "data" / "log_upload_state.json").read_text())
    assert state["files"]["agent.log"] == len(b"line-1\nline-2\nline-3\n")
    uploader2 = make_uploader(tmp_path, server)
    assert await uploader2.flush_all() == 0


async def test_失败不推进offset_不删文件(tmp_path: Path) -> None:
    server = FakeServer()
    server.ok = False
    uploader = make_uploader(tmp_path, server)
    rotated = write_log(tmp_path, "old-log\n", name="agent.2026-01-01.log")

    assert await uploader.flush_all() == 0
    assert rotated.exists()  # 上传失败不删
    assert server.chunks == []

    server.ok = True
    assert await uploader.flush_all() == 1  # 恢复后补齐
    assert server.chunks[0]["content"] == "old-log\n"


async def test_轮转文件上传完成后删除(tmp_path: Path) -> None:
    server = FakeServer()
    uploader = make_uploader(tmp_path, server)
    rotated = write_log(tmp_path, "rotated-content\n", name="agent.2026-01-01.log")
    active = write_log(tmp_path, "active-content\n")

    assert await uploader.flush_all() == 2
    assert not rotated.exists()  # 轮转文件整体上传完成 → 删除节省磁盘
    assert active.exists()  # 活跃文件永不删除
    state = json.loads((tmp_path / "data" / "log_upload_state.json").read_text())
    assert "agent.2026-01-01.log" not in state["files"]
    assert state["files"]["agent.log"] == len(b"active-content\n")


async def test_按行边界截断(tmp_path: Path) -> None:
    server = FakeServer()
    uploader = make_uploader(tmp_path, server, max_chunk_bytes=4096)
    content = "".join(f"log-line-{i}\n" for i in range(1000))
    write_log(tmp_path, content)

    uploaded = await uploader.flush_all()
    assert uploaded > 1  # 被切成多个 chunk
    for chunk in server.chunks:
        assert chunk["content"].endswith("\n")  # 行边界完整
        assert len(chunk["content"].encode()) <= 4096
    assert "".join(c["content"] for c in server.chunks) == content


async def test_截断后轮转重置offset(tmp_path: Path) -> None:
    server = FakeServer()
    uploader = make_uploader(tmp_path, server)
    write_log(tmp_path, "a" * 100 + "\n")
    await uploader.flush_all()

    # 模拟文件被替换为更小的新文件（轮转）
    write_log(tmp_path, "new\n")
    assert await uploader.flush_all() == 1
    assert server.chunks[-1]["content"] == "new\n"


async def test_错误触发与防抖(tmp_path: Path) -> None:
    server = FakeServer()
    uploader = make_uploader(tmp_path, server)

    uploader.notify_error(None)
    assert uploader._pending_error is True

    # 模拟刚完成一次错误触发上传 → 防抖窗口内忽略新信号
    uploader._pending_error = False
    uploader._last_error_flush = time.monotonic()
    uploader.notify_error(None)
    assert uploader._pending_error is False

    # 防抖窗口过后恢复响应
    uploader._last_error_flush = time.monotonic() - uploader._debounce - 1
    uploader.notify_error(None)
    assert uploader._pending_error is True
