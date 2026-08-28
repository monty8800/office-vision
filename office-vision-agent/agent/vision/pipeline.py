"""视觉流水线：Camera → Detector → Presence → Pose → Plugins → EventBus。

约束：
- 流水线不访问数据库、不控制硬件，只发布事件
- Presence 休眠（SLEEPING）时停止 MediaPipe 与全部插件，
  仅保留低频（sleep_fps）人员检测用于唤醒；
  V1 复用当前 BaseDetector 实现，后续可替换为更轻量的传感器/算法
- 所有模块协作只通过 EventBus，禁止直接互相调用
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import replace

from loguru import logger

from agent.events.bus import EventBus
from agent.events.types import PresenceResumed, PresenceSleeping
from agent.plugins.manager import PluginManager
from agent.presence.manager import PresenceManager, PresenceState
from agent.vision.camera.base import BaseCamera
from agent.vision.detector.base import BaseDetector, BasePoseDetector
from agent.vision.frame import Frame, VisionContext


class VisionPipeline:
    """串联采集、检测、Presence、插件的主循环。"""

    def __init__(
        self,
        camera: BaseCamera,
        detector: BaseDetector,
        pose: BasePoseDetector,
        presence: PresenceManager,
        plugins: PluginManager,
        bus: EventBus,
        process_fps: float = 5.0,
        sleep_fps: float = 0.5,
        frame_tap: Callable[[VisionContext], None] | None = None,
    ) -> None:
        self._camera = camera
        self._detector = detector
        self._pose = pose
        self._presence = presence
        self._plugins = plugins
        self._bus = bus
        self._process_fps = max(process_fps, 0.1)
        self._sleep_fps = max(sleep_fps, 0.05)
        # 可选观测钩子（监控中心注入）；生产环境为 None，零开销
        self._frame_tap = frame_tap
        self._running = False
        self._last_index = -1

        # Presence 生命周期 → 插件联动（只经事件，不直接调用）
        bus.subscribe_sync(PresenceSleeping, self._on_sleeping)
        bus.subscribe_sync(PresenceResumed, self._on_resumed)

    # ---- 生命周期 ----

    def open(self) -> bool:
        """打开摄像头；失败返回 False（如 macOS 未授权）。"""
        return self._camera.start()

    def shutdown(self) -> None:
        """停止主循环并释放摄像头与姿态模型资源。"""
        self._running = False
        self._pose.close()
        self._camera.stop()
        logger.info("视觉流水线已停止")

    async def run(self) -> None:
        """主循环：按 Presence 状态动态切换处理频率。"""
        self._running = True
        logger.info(
            "视觉流水线启动（处理 {} fps / 休眠探测 {} fps）",
            self._process_fps,
            self._sleep_fps,
        )
        while self._running:
            sleeping = self._presence.state is PresenceState.SLEEPING
            if sleeping:
                # 08:00 准时开启：若已过凌晨窗口结束点，强制唤醒（摄像头保持开启去等上班）
                if self._presence.past_off_hours_end(time.time()):
                    for event in self._presence.force_wake():
                        await self._bus.publish(event)
                    if not self._camera.is_open:
                        self._camera.start()
                        logger.info("08:00 准时开启摄像头")
                    continue  # 进入正常循环（若无人会按工作时段阈值再休眠）
                # 深度休眠：关闭摄像头（省电/减压），每隔 wakeup_check_seconds 唤醒查一次人
                if self._camera.is_open:
                    self._camera.stop()
                    logger.info("深度休眠：摄像头已关闭（省电/减压）")
                await asyncio.sleep(self._presence.wakeup_check_seconds)
                await self._deep_sleep_check()
                continue
            fps = self._process_fps
            frame = self._camera.read()
            if frame is not None and frame.index != self._last_index:
                self._last_index = frame.index
                try:
                    await self._process_frame(frame)
                except Exception:
                    logger.exception("帧处理异常（已隔离，管线继续）")
            await asyncio.sleep(1.0 / fps)

    async def _deep_sleep_check(self) -> None:
        """深度休眠周期性唤醒：开摄像头 → 人形检测 → 有人恢复工作，无人再关闭。"""
        if not self._camera.start():
            logger.error("深度唤醒：摄像头开启失败（待下周期重试）")
            return
        # 丢前几帧等自动曝光稳定
        for _ in range(10):
            await asyncio.sleep(0.1)
            if self._camera.read() is not None:
                break
        # 在 resume_wait 窗口内连续喂人员判定；确认有人则恢复工作，否则关闭
        waiter = max(self._presence.resume_wait_seconds, 1.0)
        deadline = time.monotonic() + waiter + 2.0
        resumed = False
        while time.monotonic() < deadline:
            frame = self._camera.read()
            if frame is not None:
                detections = self._detector.detect(frame)
                person = any(d.label == "person" for d in detections)
                events = self._presence.update(person, frame.timestamp)
                for event in events:
                    await self._bus.publish(event)
                if self._presence.state is PresenceState.WORKING:
                    resumed = True
                    break
            await asyncio.sleep(1.0 / self._sleep_fps)
        if resumed:
            logger.info("深度唤醒：检测到人，恢复工作")
        else:
            self._camera.stop()
            logger.info("深度唤醒：仍无人，摄像头保持关闭")

    # ---- 单帧处理 ----

    async def _process_frame(self, frame: Frame) -> None:
        detections = self._detector.detect(frame)
        events = self._presence.update(
            any(d.label == "person" for d in detections), frame.timestamp
        )
        for event in events:
            await self._bus.publish(event)  # PresenceSleeping 发布时同步停用插件

        if not self._presence.run_full_pipeline:
            self._tap(VisionContext(frame=frame, detections=detections))
            return  # 休眠/无人：跳过 MediaPipe 与行为插件

        context = VisionContext(
            frame=frame,
            detections=detections,
            pose=self._pose.analyze(frame),
        )
        # 行为分类（可选 AI 模块）：仅当检出香烟时才注入，供 smoking 插件确认通道。
        # 无香烟检出的帧不需要分类（节省每帧一次 smoking-cls 推理）。
        if hasattr(self._detector, "classify_smoking") and any(
            d.label == "cigarette" for d in detections
        ):
            cls = self._detector.classify_smoking(frame)
            if cls is not None:
                context = replace(context, smoking_cls=cls[0], smoking_cls_conf=cls[1])
        self._tap(context)
        for event in self._plugins.process_frame(context):
            await self._bus.publish(event)

    def _tap(self, context: VisionContext) -> None:
        if self._frame_tap is None:
            return
        try:
            self._frame_tap(context)
        except Exception:
            logger.exception("frame_tap 观测钩子异常（已隔离）")

    # ---- Presence 事件联动 ----

    def _on_sleeping(self, event: PresenceSleeping) -> None:
        logger.info("进入休眠：停用 MediaPipe 与全部插件，仅保留低频人员检测")
        self._plugins.suspend()

    def _on_resumed(self, event: PresenceResumed) -> None:
        logger.info("检测到人员回归，恢复全部插件")
        self._plugins.resume()
