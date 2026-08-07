"""UVC（USB）摄像头实现：macOS / Linux / Windows 通用。

迁移自单体原型（backend/app/vision/camera/camera.py），已验证。
独立后台线程持续采集，read() 返回最新帧（丢弃旧帧，保证管线实时性）。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, cast

import cv2
import numpy as np
import numpy.typing as npt
from loguru import logger

from agent.vision.camera.base import BaseCamera
from agent.vision.frame import Frame

_REOPEN_AFTER_FAILURES = 5


@dataclass(frozen=True)
class UvcSettings:
    """UVC 摄像头参数（来自 agent.yaml 的 camera 段）。"""

    index: int = 0
    width: int = 1280
    height: int = 720
    fps: int = 30
    warmup_frames: int = 10

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> UvcSettings:
        known = {f for f in cls.__dataclass_fields__}  # noqa: C416
        return cls(**{k: v for k, v in config.items() if k in known})


class UvcCamera(BaseCamera):
    """OpenCV VideoCapture 封装（UVC/USB 摄像头）。"""

    name = "uvc"

    def __init__(self, config: dict[str, Any]) -> None:
        self._settings = UvcSettings.from_dict(config)
        self._cap: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._latest: Frame | None = None
        self._frame_index = 0

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def start(self) -> bool:
        """打开摄像头并启动采集线程；失败时返回 False（macOS 未授权等场景）。"""
        cap = cv2.VideoCapture(self._settings.index)
        if not cap.isOpened():
            logger.error(
                "无法打开摄像头 {}（macOS 请在 系统设置 > 隐私与安全性 > 摄像头 中授权）",
                self._settings.index,
            )
            return False
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._settings.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._settings.height)
        cap.set(cv2.CAP_PROP_FPS, self._settings.fps)
        # 预热：丢弃自动曝光未稳定的帧
        for _ in range(self._settings.warmup_frames):
            cap.read()
        self._cap = cap
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="camera")
        self._thread.start()
        logger.info("UVC 摄像头 {} 已启动", self._settings.index)
        return True

    def _capture_loop(self) -> None:
        consecutive_failures = 0
        while self._running:
            cap = self._cap
            ok, image = (False, None) if cap is None else cap.read()
            if not ok or image is None:
                consecutive_failures += 1
                # macOS 授权延迟生效 / 设备被抢占后，旧句柄会永久失效，需重新打开
                if consecutive_failures >= _REOPEN_AFTER_FAILURES:
                    consecutive_failures = 0
                    logger.warning("摄像头连续读帧失败，尝试重新打开")
                    self._reopen()
                else:
                    time.sleep(1.0)
                continue
            consecutive_failures = 0
            self._frame_index += 1
            frame = Frame(
                image=cast("npt.NDArray[np.uint8]", image),
                timestamp=time.time(),
                index=self._frame_index,
            )
            with self._lock:
                self._latest = frame

    def _reopen(self) -> None:
        """释放旧句柄并重新打开（仅采集线程调用）。"""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        time.sleep(1.0)
        cap = cv2.VideoCapture(self._settings.index)
        if not cap.isOpened():
            logger.warning("摄像头重新打开失败，稍后重试")
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._settings.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._settings.height)
        cap.set(cv2.CAP_PROP_FPS, self._settings.fps)
        self._cap = cap
        logger.info("摄像头已重新打开")

    def read(self) -> Frame | None:
        """获取最新帧；未启动或暂无帧时返回 None。"""
        with self._lock:
            return self._latest

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        logger.info("UVC 摄像头已停止")
