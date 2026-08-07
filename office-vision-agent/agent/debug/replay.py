"""Event Replay：事件触发自动保存 前10s + 过程 + 后10s 回放片段。

产物（data/debug/replays/<event_id>/）：
    replay.mp4    回放视频（Dashboard 点击播放）
    meta.json     事件信息 + 时间窗 + 帧数

排查误判、数据集制作、AI 优化均可直接消费本目录。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

import cv2
from loguru import logger

from agent.debug.frame_buffer import FrameBuffer
from agent.events.types import Event
from agent.vision.frame import Frame

# 默认触发回放的事件类型（后续新插件事件自动支持，只需在此追加或在配置中声明）
DEFAULT_TRIGGER_EVENTS = frozenset({"SmokingStarted", "SmokingEnded"})


class ReplayRecorder:
    """监听事件并在事件结束后截取完整回放窗口。"""

    def __init__(
        self,
        buffer: FrameBuffer,
        out_dir: Path,
        before_seconds: float = 10.0,
        after_seconds: float = 10.0,
        trigger_events: frozenset[str] = DEFAULT_TRIGGER_EVENTS,
        fps: int = 5,
    ) -> None:
        self._buffer = buffer
        self._out_dir = out_dir
        self._before = before_seconds
        self._after = after_seconds
        self._triggers = trigger_events
        self._fps = fps

    async def on_event(self, event: Event) -> None:
        if event.event_type not in self._triggers:
            return
        # 等事件过程结束 + after 秒后，再从缓冲截取完整窗口
        asyncio.create_task(self._capture(event))

    async def _capture(self, event: Event) -> None:
        await asyncio.sleep(self._after)
        anchor = event.occurred_at.timestamp()
        start, end = anchor - self._before, anchor + self._after
        frames = self._buffer.window(start, end)
        if not frames:
            logger.warning("Replay 跳过 {}：帧缓冲中无可用画面", event.event_type)
            return
        await asyncio.to_thread(self._save, event, frames, start, end)

    def _save(self, event: Event, frames: Sequence[Frame], start: float, end: float) -> None:
        target = self._out_dir / event.event_id
        target.mkdir(parents=True, exist_ok=True)
        first = frames[0]
        height, width = first.image.shape[:2]
        writer = cv2.VideoWriter(
            str(target / "replay.mp4"), cv2.VideoWriter.fourcc(*"mp4v"), self._fps, (width, height)
        )
        for item in frames:
            writer.write(item.image)
        writer.release()

        meta = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "device_id": event.device_id,
            "occurred_at": event.occurred_at.isoformat(),
            "window": {"start": start, "end": end},
            "frame_count": len(frames),
            "payload": event.payload(),
        }
        (target / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Replay 已保存: {} ({} 帧)", event.event_id, len(frames))

    def list_replays(self) -> list[dict[str, object]]:
        """列出全部回放（按时间倒序）。"""
        replays: list[dict[str, object]] = []
        if not self._out_dir.exists():
            return replays
        for meta_file in self._out_dir.glob("*/meta.json"):
            try:
                replays.append(json.loads(meta_file.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                logger.warning("Replay 元数据损坏: {}", meta_file)
        replays.sort(key=lambda r: str(r.get("occurred_at", "")), reverse=True)
        return replays

    def video_path(self, event_id: str) -> Path | None:
        path = self._out_dir / event_id / "replay.mp4"
        return path if path.exists() else None
