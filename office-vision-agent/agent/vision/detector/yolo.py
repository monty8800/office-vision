"""YOLOv11 目标检测器（基于 ultralytics，BaseDetector 的默认实现）。

V1 用于人形检测（确认画面中有人）；可选挂载自训练香烟检测权重
（detector.cigarette_weights），产出 label=cigarette 的检测结果供
smoking 插件作为强证据，权重缺失时自动降级为仅人形检测。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from agent.vision.detector.base import BaseDetector
from agent.vision.frame import Box, Detection, Frame

if TYPE_CHECKING:
    from ultralytics.engine.results import Results

PERSON_CLASS_ID = 0  # COCO


@dataclass(frozen=True)
class YoloSettings:
    """YOLO 参数（来自 agent.yaml 的 detector 段）。"""

    weights: str = "models/yolo11n.pt"
    confidence: float = 0.45
    person_only: bool = True
    cigarette_weights: str = ""  # 自训练香烟模型权重路径，空则不启用
    cigarette_confidence: float = 0.25

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> YoloSettings:
        known = {f for f in cls.__dataclass_fields__}  # noqa: C416
        return cls(**{k: v for k, v in config.items() if k in known})


class YoloDetector(BaseDetector):
    """YOLOv11 检测器，模型懒加载（首次 detect 时才载入权重）。"""

    name = "yolo"

    def __init__(self, config: dict[str, Any]) -> None:
        self._settings = YoloSettings.from_dict(config)
        self._model: Any | None = None
        self._cigarette_model: Any | None = None
        self._cigarette_unavailable = False  # 权重缺失时降级，不反复告警

    def _ensure_model(self) -> Any:
        if self._model is None:
            from ultralytics import YOLO  # type: ignore[attr-defined]  # noqa: PLC0415

            weights = self._settings.weights
            logger.info("加载 YOLO 权重: {}", weights)
            self._model = YOLO(weights)
        return self._model

    def _ensure_cigarette_model(self) -> Any | None:
        """懒加载香烟检测模型；未配置或权重缺失时返回 None（降级）。"""
        if self._cigarette_model is not None or self._cigarette_unavailable:
            return self._cigarette_model
        weights = self._settings.cigarette_weights
        if not weights:
            self._cigarette_unavailable = True
            return None
        if not Path(weights).exists():
            logger.warning("香烟检测权重不存在，降级为仅人形检测: {}", weights)
            self._cigarette_unavailable = True
            return None
        from ultralytics import YOLO  # type: ignore[attr-defined]  # noqa: PLC0415

        logger.info("加载香烟检测权重: {}", weights)
        self._cigarette_model = YOLO(weights)
        return self._cigarette_model

    def _detect_cigarettes(self, frame: Frame) -> list[Detection]:
        """第二模型：自训练香烟检测（小目标，独立置信度阈值）。"""
        model = self._ensure_cigarette_model()
        if model is None:
            return []
        results: list[Results] = model(frame.image, verbose=False)
        detections: list[Detection] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for i in range(len(boxes)):
                confidence = float(boxes.conf[i].item())
                if confidence < self._settings.cigarette_confidence:
                    continue
                x1, y1, x2, y2 = (float(v) for v in boxes.xyxy[i].tolist())
                class_id = int(boxes.cls[i].item())
                label = result.names.get(class_id, str(class_id))
                detections.append(
                    Detection(
                        class_id=class_id,
                        label=str(label),
                        confidence=confidence,
                        box=Box(x1, y1, x2, y2),
                    )
                )
        return detections

    def detect(self, frame: Frame) -> list[Detection]:
        model = self._ensure_model()
        results: list[Results] = model(frame.image, verbose=False)
        detections: list[Detection] = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for i in range(len(boxes)):
                class_id = int(boxes.cls[i].item())
                if self._settings.person_only and class_id != PERSON_CLASS_ID:
                    continue
                confidence = float(boxes.conf[i].item())
                if confidence < self._settings.confidence:
                    continue
                x1, y1, x2, y2 = (float(v) for v in boxes.xyxy[i].tolist())
                label = result.names.get(class_id, str(class_id))
                detections.append(
                    Detection(
                        class_id=class_id,
                        label=str(label),
                        confidence=confidence,
                        box=Box(x1, y1, x2, y2),
                    )
                )
        detections.extend(self._detect_cigarettes(frame))
        return detections
