"""日志上传器：本地日志文件增量上报到 Server（POST /api/logs）。

机制：
1. 每周期扫描日志目录，按 mtime 升序处理（先轮转文件、后当前活跃文件）
2. 按字节 offset 增量读取（状态持久化到 log_upload_state.json）
3. 上传成功才推进 offset；轮转文件整体上传完成后立即删除（节省磁盘），失败不删
4. 除定时上传外，ERROR 级日志经 notify_error 信号提前唤醒（带防抖）

日志非业务事件：不走 EventBus/离线队列，上传失败下周期重试即可。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
from loguru import logger


class LogUploader:
    """日志文件 → HTTP 增量上传；作为独立协程随主循环运行。"""

    def __init__(
        self,
        server_url: str,
        device_id: str,
        log_file: Path,
        state_path: Path,
        interval_seconds: float = 300.0,
        error_debounce_seconds: float = 30.0,
        max_chunk_bytes: int = 262144,
        component: str = "agent",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._device_id = device_id
        self._log_file = Path(log_file)
        self._state_path = Path(state_path)
        self._interval = max(interval_seconds, 5.0)
        self._debounce = max(error_debounce_seconds, 1.0)
        self._max_chunk = max(max_chunk_bytes, 4096)
        self._component = component
        self._client = client or httpx.AsyncClient(base_url=server_url, timeout=10.0)
        self._state: dict[str, int] = self._load_state()
        self._running = False
        self._wakeup = asyncio.Event()
        self._pending_error = False
        self._last_error_flush = 0.0
        self._loop: asyncio.AbstractEventLoop | None = None

    # ---- 生命周期 ----

    async def run(self) -> None:
        self._running = True
        self._loop = asyncio.get_running_loop()
        logger.info("日志上传器启动（间隔 {}s）", self._interval)
        while self._running:
            with contextlib.suppress(TimeoutError):  # 超时 = 定时周期到
                await asyncio.wait_for(self._wakeup.wait(), timeout=self._interval)
            self._wakeup.clear()
            if not self._running:
                break
            trigger = "error" if self._pending_error else "periodic"
            self._pending_error = False
            if trigger == "error":
                self._last_error_flush = time.monotonic()
            try:
                await self.flush_all(trigger)
            except Exception:
                logger.exception("日志上传异常（下周期重试）")

    async def stop(self) -> None:
        """停止前尽力冲刷一次，随后释放资源。"""
        self._running = False
        self._wakeup.set()
        try:
            await self.flush_all("periodic")
        except Exception:
            logger.exception("停止前冲刷失败（日志保留在本地）")
        await self._client.aclose()
        logger.info("日志上传器已停止")

    def notify_error(self, _message: object) -> None:
        """Loguru ERROR 级 sink：提前唤醒上传（可能从任意线程调用）。"""
        if time.monotonic() - self._last_error_flush < self._debounce:
            return
        self._pending_error = True
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._wakeup.set)

    # ---- 上传主逻辑 ----

    async def flush_all(self, trigger: str = "periodic") -> int:
        """处理全部候选文件；返回成功上传的 chunk 数。"""
        uploaded = 0
        for path, is_active in self._candidate_files():
            uploaded += await self._flush_file(path, is_active, trigger)
        return uploaded

    def _candidate_files(self) -> list[tuple[Path, bool]]:
        """日志目录内活跃文件 + 轮转文件；按 mtime 升序，活跃文件始终最后。

        Loguru 轮转命名为 <stem>.<时间戳>.log，故按 stem 前缀匹配。
        """
        log_dir = self._log_file.parent
        if not log_dir.is_dir():
            return []
        files = [p for p in log_dir.glob(f"{self._log_file.stem}*") if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime)
        return [(p, p == self._log_file) for p in files]

    async def _flush_file(self, path: Path, is_active: bool, trigger: str) -> int:
        uploaded = 0
        size = path.stat().st_size
        offset = self._state.get(path.name, 0)
        if size < offset:  # 文件被截断/替换（轮转）
            offset = 0
        while offset < size:
            chunk = self._read_chunk(path, offset)
            if not chunk:
                break
            if not await self._post_chunk(chunk, trigger):
                break  # 上传失败：offset 不推进，下周期重试
            offset += len(chunk)
            self._state[path.name] = offset
            self._save_state()
            uploaded += 1
            size = path.stat().st_size  # 活跃文件可能继续增长
        if not is_active and offset >= path.stat().st_size:
            path.unlink(missing_ok=True)  # 整体上传完成，删除轮转文件节省磁盘
            self._state.pop(path.name, None)
            self._save_state()
        return uploaded

    def _read_chunk(self, path: Path, offset: int) -> bytes:
        with path.open("rb") as fh:
            fh.seek(offset)
            data = fh.read(self._max_chunk)
        if len(data) < self._max_chunk:
            return data
        cut = data.rfind(b"\n")  # 按行边界截断，避免日志行被拆成两半
        return data[: cut + 1] if cut > 0 else data

    async def _post_chunk(self, chunk: bytes, trigger: str) -> bool:
        payload = {
            "chunk_id": uuid.uuid4().hex,
            "device_id": self._device_id,
            "component": self._component,
            "trigger": trigger,
            "logged_at": datetime.now(UTC).isoformat(),
            "content": chunk.decode("utf-8", errors="replace"),
        }
        try:
            response = await self._client.post("/api/logs", json=payload)
            response.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            logger.warning("日志上传失败（下周期重试）: {}", exc)
            return False

    # ---- offset 状态持久化 ----

    def _load_state(self) -> dict[str, int]:
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            files = raw.get("files", {})
            return {name: int(offset) for name, offset in files.items()}
        except (OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        tmp = self._state_path.with_suffix(self._state_path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps({"files": self._state}), encoding="utf-8")
            tmp.replace(self._state_path)
        except OSError:
            logger.warning("日志上传状态写入失败: {}", self._state_path)
