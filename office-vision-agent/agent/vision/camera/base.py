"""摄像头抽象层（Platform Agnostic）。

BaseCamera 统一接口，所有硬件经此隔离，核心逻辑不感知平台：
- UvcCamera        USB/UVC 摄像头（macOS / Linux / Windows）
- RtspCamera       RTSP 网络摄像头（后续）
- RpiCamera        Raspberry Pi Camera（后续）
- Esp32Camera      ESP32 Camera（后续）

接口：start() / read() -> Frame | None / stop() / is_open

新增硬件支持 = 新增一个 BaseCamera 子类 + 在 create_camera 注册，
禁止修改管线或业务代码。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent.vision.frame import Frame


class BaseCamera(ABC):
    """所有摄像头实现的统一接口。"""

    name: str = "base"

    @abstractmethod
    def start(self) -> bool:
        """打开设备；失败返回 False（如未授权、设备不存在）。"""

    @abstractmethod
    def read(self) -> Frame | None:
        """获取最新帧；未启动或暂无帧返回 None。实现应丢弃旧帧保证实时性。"""

    @abstractmethod
    def stop(self) -> None:
        """释放设备资源。"""

    @property
    def is_open(self) -> bool:
        return False

    def __enter__(self) -> BaseCamera:
        if not self.start():
            msg = f"摄像头 {self.name} 启动失败"
            raise RuntimeError(msg)
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


def create_camera(camera_type: str, config: dict[str, Any]) -> BaseCamera:
    """按配置创建摄像头实例（硬件抽象的唯一入口）。

    config 来自 agent.yaml 的 camera 段。未知类型立即报错，禁止静默降级。
    """
    kind = camera_type.strip().lower()
    if kind == "uvc":
        from agent.vision.camera.uvc import UvcCamera  # noqa: PLC0415

        return UvcCamera(config)
    if kind in {"rtsp", "rpicam", "esp32"}:
        msg = f"摄像头类型 {camera_type!r} 尚未实现（Platform Agnostic 路线图中）"
        raise NotImplementedError(msg)
    msg = f"未知摄像头类型: {camera_type!r}，支持: uvc | rtsp | rpicam | esp32"
    raise ValueError(msg)
