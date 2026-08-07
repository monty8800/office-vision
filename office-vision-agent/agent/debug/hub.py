"""DebugHub：Debug Center 的中枢。

数据来源严格遵守 Spec：
- 事件流 / 行为状态 / 插件状态 → 全部来自 EventBus 订阅，不读业务内部状态
- 画面 / Overlay / 距离 → 来自管线注入的 frame_tap 钩子
- 性能数据 → PerfCollector 打点（同样经 frame_tap 与事件驱动）
"""

from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
from loguru import logger

if TYPE_CHECKING:
    from loguru import Message

from agent.debug.annotator import OverlayToggles, annotate, hand_mouth_distance
from agent.debug.config import DebugSettings
from agent.debug.frame_buffer import FrameBuffer
from agent.debug.perf import PerfCollector
from agent.debug.replay import ReplayRecorder
from agent.events.bus import EventBus
from agent.events.types import (
    AgentAlive,
    Event,
    PresenceResumed,
    PresenceSleeping,
    SeatEmpty,
    SeatOccupied,
)
from agent.vision.frame import VisionContext

_TIMELINE_LIMIT = 500
_LOG_LIMIT = 500


class DebugHub:
    """聚合帧、事件、性能与状态，供 Debug HTTP API 消费。"""

    def __init__(self, device_id: str, settings: DebugSettings, bus: EventBus) -> None:
        self._device_id = device_id
        self.settings = settings
        self.buffer = FrameBuffer(settings.frame_buffer_seconds)
        self.perf = PerfCollector()
        self.toggles = OverlayToggles()
        self.replay = ReplayRecorder(
            self.buffer,
            Path(settings.data_dir) / "replays",
            before_seconds=settings.replay_before_seconds,
            after_seconds=settings.replay_after_seconds,
            snapshot_interval=settings.replay_snapshot_interval,
        )
        self._timeline: deque[dict[str, Any]] = deque(maxlen=_TIMELINE_LIMIT)
        self._labels_path = Path(settings.data_dir) / "labels.jsonl"

        # 实时日志：仅内存环形缓冲，不落盘；进程退出即清空
        self._logs: deque[dict[str, str]] = deque(maxlen=_LOG_LIMIT)
        logger.add(self._log_sink, level="INFO")

        # 派生状态（只由事件推导）
        self._presence_state = "waiting"
        self._current_behavior = "idle"
        self._behavior_since: str | None = None
        self._plugins_suspended = False
        self._plugin_names: list[str] = []
        self._plugin_debug: Callable[[], list[dict[str, Any]]] | None = None

        # 最近帧上下文（Overlay 渲染用）
        self._latest_context: VisionContext | None = None
        self._latest_event_text = ""

        # 订阅全部事件：时间轴、状态派生、回放触发都只经 EventBus
        bus.subscribe(Event, self._on_event)

    # ---- 装配期注册（配置信息，非内部状态读取） ----

    def register_plugins(
        self,
        names: list[str],
        debug_provider: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> None:
        self._plugin_names = list(names)
        self._plugin_debug = debug_provider

    # ---- 管线帧钩子（唯一与视觉层的接触点） ----

    def on_frame(self, context: VisionContext) -> None:
        self.perf.tick_camera()
        self.buffer.add(context.frame)
        self._latest_context = context
        if context.pose.has_face or context.pose.hands:
            self.perf.tick_ai()

    # ---- 事件订阅（全部调试数据的来源） ----

    async def _on_event(self, event: Event) -> None:
        if isinstance(event, AgentAlive):
            return  # 心跳仅用于 Server 在线判定，不进调试时间轴/状态派生
        self._latest_event_text = f"{event.event_type} @ {event.occurred_at:%H:%M:%S}"
        self._timeline.append(
            {
                "time": event.occurred_at.isoformat(),
                "event_type": event.event_type,
                "device_id": event.device_id,
                "payload": event.payload(),
            }
        )
        self._derive_state(event)
        if self.settings.replay:
            await self.replay.on_event(event)

    def _derive_state(self, event: Event) -> None:
        if isinstance(event, SeatOccupied):
            self._presence_state = "working"
            self._plugins_suspended = False
        elif isinstance(event, SeatEmpty):
            self._presence_state = "away"
        elif isinstance(event, PresenceSleeping):
            self._presence_state = "sleeping"
            self._plugins_suspended = True
            self._current_behavior = "idle"
        elif isinstance(event, PresenceResumed):
            self._presence_state = "working"
            self._plugins_suspended = False
        elif event.event_type == "SmokingStarted":
            self._current_behavior = "smoking"
            self._behavior_since = event.occurred_at.isoformat()
        elif event.event_type == "SmokingEnded":
            self._current_behavior = "idle"
            self._behavior_since = None

    # ---- 对外快照 ----

    def state_snapshot(self) -> dict[str, Any]:
        distance = None
        if self._latest_context is not None:
            measured = hand_mouth_distance(self._latest_context.pose)
            if measured is not None:
                distance = round(measured[0], 1)
        duration = None
        if self._behavior_since is not None:
            started = datetime.fromisoformat(self._behavior_since)
            duration = round(time.time() - started.timestamp(), 1)
        return {
            "device_id": self._device_id,
            "behavior": {
                "presence": self._presence_state,
                "current": self._current_behavior,
                "since": self._behavior_since,
                "duration_seconds": duration,
                "hand_mouth_distance_px": distance,
            },
            "plugins": [
                {
                    "name": name,
                    "status": "suspended" if self._plugins_suspended else "running",
                    **self._plugin_debug_by_name().get(name, {}),
                }
                for name in self._plugin_names
            ],
            "performance": self.perf.snapshot() if self.settings.performance else {},
            "overlays": self.toggles.as_dict(),
            "frame_buffer_frames": len(self.buffer),
        }

    def timeline(self, limit: int = 100) -> list[dict[str, Any]]:
        items = list(self._timeline)
        return items[-limit:]

    def logs(self, limit: int = 200) -> list[dict[str, str]]:
        items = list(self._logs)
        return items[-limit:]

    def _log_sink(self, message: Message) -> None:
        """loguru 汇聚点：只入内存队列，不产生任何新日志（避免递归）。"""
        record = message.record
        self._logs.append(
            {
                "time": record["time"].strftime("%H:%M:%S"),
                "level": record["level"].name,
                "message": record["message"],
            }
        )

    def _plugin_debug_by_name(self) -> dict[str, dict[str, Any]]:
        """插件调试快照按名称索引（provider 未注册或异常时为空）。"""
        if self._plugin_debug is None:
            return {}
        try:
            infos = self._plugin_debug()
        except Exception:
            logger.exception("插件 debug_info 采集失败")
            return {}
        result: dict[str, dict[str, Any]] = {}
        for info in infos:
            name = info.get("name")
            if isinstance(name, str):
                stripped = {k: v for k, v in info.items() if k != "name"}
                result[name] = stripped
        return result

    def render_jpeg(self) -> bytes | None:
        """渲染最新帧 + Overlay，返回 JPEG 字节；无帧返回 None。"""
        context = self._latest_context
        if context is None or not self.settings.overlay:
            frame = self.buffer.latest()
            if frame is None:
                return None
            ok, encoded = cv2.imencode(".jpg", frame.image)
            return encoded.tobytes() if ok else None
        perf = self.perf.snapshot()
        state_text = f"State: {self._presence_state} | Behavior: {self._current_behavior}"
        fps_text = f"Camera FPS: {perf['camera_fps']} | AI FPS: {perf['ai_fps']}"
        canvas = annotate(
            context.frame.image,
            context,
            self.toggles,
            state_text=state_text,
            fps_text=fps_text,
            event_text=self._latest_event_text,
        )
        ok, encoded = cv2.imencode(".jpg", canvas)
        return encoded.tobytes() if ok else None

    def render_raw_jpeg(self) -> bytes | None:
        """返回最新原始帧（无 Overlay，高质量 JPEG），供数据集采集使用。"""
        frame = self.buffer.latest()
        if frame is None:
            return None
        ok, encoded = cv2.imencode(".jpg", frame.image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        return encoded.tobytes() if ok else None

    # ---- Snapshot 与 Label Mode ----

    def save_snapshot(self) -> dict[str, Any] | None:
        """一键截图：图片 + Overlay + 当前 Event + 当前状态。"""
        if not self.settings.save_snapshot:
            return None
        jpeg = self.render_jpeg()
        if jpeg is None:
            return None
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out_dir = Path(self.settings.data_dir) / "snapshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        image_path = out_dir / f"snapshot-{stamp}.jpg"
        image_path.write_bytes(jpeg)
        meta = self.state_snapshot() | {"latest_event": self._latest_event_text}
        meta_path = out_dir / f"snapshot-{stamp}.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Snapshot 已保存: {}", image_path.name)
        return {"image": str(image_path), "meta": str(meta_path), "state": meta}

    def record_label(self, event_id: str, verdict: str, note: str = "") -> dict[str, Any]:
        """Label Mode（接口预留）：人工确认识别结果，未来自动生成训练数据集。"""
        if verdict not in {"correct", "wrong"}:
            msg = f"verdict 必须是 correct/wrong，收到: {verdict!r}"
            raise ValueError(msg)
        self._labels_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "event_id": event_id,
            "verdict": verdict,
            "note": note,
            "labeled_at": datetime.now().isoformat(),
        }
        with self._labels_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record
