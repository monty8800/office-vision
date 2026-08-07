"""性能采集：CPU / Memory / Camera FPS / AI FPS / Inference / Queue / Latency。"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from typing import Any

import psutil


class PerfCollector:
    """滑动窗口计 FPS；CPU/内存来自 psutil（进程级）。"""

    def __init__(self, window_seconds: float = 5.0) -> None:
        self._window = window_seconds
        self._camera_ticks: deque[float] = deque()
        self._ai_ticks: deque[float] = deque()
        self._inference_seconds: deque[float] = deque(maxlen=50)
        self._queue_provider: Callable[[], int] | None = None
        self._process = psutil.Process()
        psutil.cpu_percent(interval=None)  # 首次调用初始化

    def set_queue_provider(self, provider: Callable[[], int]) -> None:
        self._queue_provider = provider

    # ---- 打点 ----

    def tick_camera(self) -> None:
        self._camera_ticks.append(time.monotonic())

    def tick_ai(self) -> None:
        self._ai_ticks.append(time.monotonic())

    def record_inference(self, seconds: float) -> None:
        self._inference_seconds.append(seconds)

    # ---- 快照 ----

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_mb": round(self._process.memory_info().rss / 1024 / 1024, 1),
            "camera_fps": self._fps(self._camera_ticks, now),
            "ai_fps": self._fps(self._ai_ticks, now),
            "inference_ms": self._avg_ms(),
            "queue_length": self._queue_provider() if self._queue_provider else 0,
            "latency_ms": self._latency_ms(now),
        }

    def _fps(self, ticks: deque[float], now: float) -> float:
        while ticks and now - ticks[0] > self._window:
            ticks.popleft()
        return round(len(ticks) / self._window, 1)

    def _avg_ms(self) -> float:
        if not self._inference_seconds:
            return 0.0
        return round(sum(self._inference_seconds) / len(self._inference_seconds) * 1000, 1)

    def _latency_ms(self, now: float) -> float:
        """最后一帧到达至今的时延（衡量管线是否卡死）。"""
        if not self._camera_ticks:
            return 0.0
        return round((now - self._camera_ticks[-1]) * 1000, 1)
