"""Event Replay：事件触发自动保存 前10s + 过程 + 后10s 回放片段。

为节省磁盘不录制视频，改为按固定间隔抽帧保存 JPEG 截图。

产物（data/monitor/replays/<event_id>/）：
    frames/*.jpg  回放截图（Dashboard 点击浏览）
    meta.json     事件信息 + 时间窗 + 帧数 + 截图清单

排查误判、数据集制作、AI 优化均可直接消费本目录。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from pathlib import Path

import cv2
from loguru import logger

from agent.events.types import Event
from agent.monitor.frame_buffer import FrameBuffer
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
        snapshot_interval: float = 1.0,
    ) -> None:
        self._buffer = buffer
        self._out_dir = out_dir
        self._before = before_seconds
        self._after = after_seconds
        self._triggers = trigger_events
        self._interval = max(snapshot_interval, 0.1)

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
        frames_dir = target / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        # 按间隔抽帧保存 JPEG，首帧必留
        names: list[str] = []
        last_saved = float("-inf")
        for item in frames:
            if item.timestamp - last_saved < self._interval:
                continue
            name = f"{len(names):04d}.jpg"
            ok, encoded = cv2.imencode(".jpg", item.image, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ok:
                logger.warning("Replay 截图编码失败: {} @ {:.2f}", event.event_id, item.timestamp)
                continue
            (frames_dir / name).write_bytes(encoded.tobytes())
            names.append(name)
            last_saved = item.timestamp

        meta = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "device_id": event.device_id,
            "occurred_at": event.occurred_at.isoformat(),
            "window": {"start": start, "end": end},
            "frame_count": len(frames),
            "snapshot_interval": self._interval,
            "snapshots": names,
            "payload": event.payload(),
        }
        (target / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Replay 已保存: {} ({} 张截图)", event.event_id, len(names))

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

    def snapshot_path(self, event_id: str, name: str) -> Path | None:
        """返回指定回放截图路径；文件名必须存在于该回放的 frames 目录。"""
        path = self._out_dir / event_id / "frames" / name
        if path.parent.parent != (self._out_dir / event_id) or not path.is_file():
            return None
        return path
