"""视觉层基础数据结构：帧、目标框、检测结果、姿态特征。

纯数据结构，不含任何平台/模型依赖。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class Frame:
    """单帧图像及其元数据。"""

    image: npt.NDArray[np.uint8]  # BGR，OpenCV 约定
    timestamp: float  # epoch 秒
    index: int = 0

    @property
    def width(self) -> int:
        return self.image.shape[1]

    @property
    def height(self) -> int:
        return self.image.shape[0]


@dataclass(frozen=True)
class Box:
    """目标框（像素坐标，左上 + 右下）。"""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    def expand(self, factor: float) -> Box:
        """以中心为基准按比例扩大。"""
        dw = self.width * (factor - 1) / 2
        dh = self.height * (factor - 1) / 2
        return Box(self.x1 - dw, self.y1 - dh, self.x2 + dw, self.y2 + dh)

    def contains(self, x: float, y: float) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def iou(self, other: Box) -> float:
        ix1, iy1 = max(self.x1, other.x1), max(self.y1, other.y1)
        ix2, iy2 = min(self.x2, other.x2), min(self.y2, other.y2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        union = self.width * self.height + other.width * other.height - inter
        return inter / union if union > 0 else 0.0

    def as_int_tuple(self) -> tuple[int, int, int, int]:
        return int(self.x1), int(self.y1), int(self.x2), int(self.y2)


@dataclass(frozen=True)
class Detection:
    """单个目标检测结果。"""

    class_id: int
    label: str
    confidence: float
    box: Box


@dataclass(frozen=True)
class HandFeatures:
    """单只手的几何特征（像素坐标）。"""

    wrist: tuple[float, float]
    thumb_tip: tuple[float, float]
    index_tip: tuple[float, float]
    middle_tip: tuple[float, float]
    handedness: str = "unknown"
    confidence: float = 0.0

    @property
    def fingertips(self) -> tuple[tuple[float, float], ...]:
        return (self.thumb_tip, self.index_tip, self.middle_tip)


@dataclass(frozen=True)
class PoseFeatures:
    """单帧姿态特征（面部 + 手部）。"""

    mouth_box: Box | None = None
    hands: list[HandFeatures] = field(default_factory=list)

    @property
    def has_face(self) -> bool:
        return self.mouth_box is not None


@dataclass(frozen=True)
class VisionContext:
    """分发给行为检测器的单帧视觉上下文（只含特征，不含业务语义）。"""

    frame: Frame
    detections: list[Detection] = field(default_factory=list)
    pose: PoseFeatures = field(default_factory=PoseFeatures)
    # 行为分类（如 smoking/normal）：可选 AI 模块产出，无模型时为 None/0.0。
    # 供 smoking 插件作为第三重确认通道（降低误检）。
    smoking_cls: str | None = None
    smoking_cls_conf: float = 0.0

    @property
    def has_person(self) -> bool:
        return any(d.label == "person" for d in self.detections)
