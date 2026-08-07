"""帧环形缓冲：保留最近 N 秒画面，供 Replay 与 Snapshot 使用。"""

from __future__ import annotations

import threading
from collections import deque

from agent.vision.frame import Frame


class FrameBuffer:
    """线程安全的按时间窗口淘汰的帧缓冲。"""

    def __init__(self, capacity_seconds: float = 30.0) -> None:
        self._capacity = max(capacity_seconds, 1.0)
        self._frames: deque[Frame] = deque()
        self._lock = threading.Lock()

    def add(self, frame: Frame) -> None:
        with self._lock:
            self._frames.append(frame)
            cutoff = frame.timestamp - self._capacity
            while self._frames and self._frames[0].timestamp < cutoff:
                self._frames.popleft()

    def window(self, start: float, end: float) -> list[Frame]:
        """取 [start, end] 时间窗内的全部帧（按时间升序）。"""
        with self._lock:
            return [f for f in self._frames if start <= f.timestamp <= end]

    def latest(self) -> Frame | None:
        with self._lock:
            return self._frames[-1] if self._frames else None

    def __len__(self) -> int:
        with self._lock:
            return len(self._frames)
