"""检测器抽象层（AI 模块可替换，不得写死任何具体实现）。

BaseDetector 统一接口：
- YoloDetector             ultralytics YOLOv11（当前默认，人形检测）
- CoreMlDetector           Apple Neural Engine（后续）
- TensorRtDetector / OpenVinoDetector / TfliteDetector（后续）

BasePoseDetector 统一接口（姿态/关键点特征提取）：
- MediaPipePoseDetector    MediaPipe Tasks（当前默认）

接口：detect(frame) -> list[Detection] / analyze(frame) -> PoseFeatures

新增推理引擎 = 新增一个子类 + 在工厂注册，禁止修改管线或插件代码。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent.vision.frame import Detection, Frame, PoseFeatures


class BaseDetector(ABC):
    """目标检测器统一接口。模型应懒加载（首次 detect 时才载入权重）。"""

    name: str = "base"

    @abstractmethod
    def detect(self, frame: Frame) -> list[Detection]:
        """对单帧执行检测，返回目标列表（可为空）。"""


class BasePoseDetector(ABC):
    """姿态/关键点特征提取器统一接口。只输出几何特征，不做行为语义解释。"""

    name: str = "base"

    @abstractmethod
    def analyze(self, frame: Frame) -> PoseFeatures:
        """提取单帧姿态特征；实现应保证异常时返回空特征而不中断管线。"""

    def close(self) -> None:  # noqa: B027  默认无操作，子类按需覆写
        """释放模型资源。"""


def create_detector(detector_type: str, config: dict[str, Any]) -> BaseDetector:
    """按配置创建目标检测器（AI 模块替换的唯一入口）。"""
    kind = detector_type.strip().lower()
    if kind == "yolo":
        from agent.vision.detector.yolo import YoloDetector  # noqa: PLC0415

        return YoloDetector(config)
    if kind in {"coreml", "tensorrt", "openvino", "tflite"}:
        msg = f"检测器 {detector_type!r} 尚未实现（AI 可替换路线图中）"
        raise NotImplementedError(msg)
    msg = f"未知检测器类型: {detector_type!r}，支持: yolo | coreml | tensorrt | openvino | tflite"
    raise ValueError(msg)


def create_pose_detector(pose_type: str, config: dict[str, Any]) -> BasePoseDetector:
    """按配置创建姿态检测器。"""
    kind = pose_type.strip().lower()
    if kind == "mediapipe":
        from agent.vision.detector.mediapipe_pose import MediaPipePoseDetector  # noqa: PLC0415

        return MediaPipePoseDetector(config)
    msg = f"未知姿态检测器类型: {pose_type!r}，支持: mediapipe"
    raise ValueError(msg)
