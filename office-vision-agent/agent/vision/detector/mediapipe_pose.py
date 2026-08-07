"""MediaPipe 姿态估计（BasePoseDetector 的默认实现）。

面部关键点（嘴部区域）+ 手部关键点，输出纯几何特征（PoseFeatures），
供插件做行为启发式判断；本模块不做任何行为语义解释。
迁移自单体原型，已验证。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from agent.vision.detector.base import BasePoseDetector
from agent.vision.frame import Box, Frame, HandFeatures, PoseFeatures

# MediaPipe FaceLandmarker 关键点索引
_MOUTH_LANDMARKS = (61, 291, 13, 14)  # 左右嘴角 + 上下唇中
# MediaPipe HandLandmarker 关键点索引
HAND_WRIST = 0
HAND_THUMB_TIP = 4
HAND_INDEX_TIP = 8
HAND_MIDDLE_TIP = 12


@dataclass(frozen=True)
class MediaPipeSettings:
    """MediaPipe 参数（来自 agent.yaml 的 pose 段）。"""

    face_model: str = "models/face_landmarker.task"
    hand_model: str = "models/hand_landmarker.task"
    num_hands: int = 2

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> MediaPipeSettings:
        known = {f for f in cls.__dataclass_fields__}  # noqa: C416
        return cls(**{k: v for k, v in config.items() if k in known})


def _to_px(landmarks: Any, idx: int, width: float, height: float) -> tuple[float, float]:
    """归一化关键点 → 像素坐标。"""
    return (landmarks[idx].x * width, landmarks[idx].y * height)


class MediaPipePoseDetector(BasePoseDetector):
    """MediaPipe Tasks 封装（FaceLandmarker + HandLandmarker），懒加载模型。"""

    name = "mediapipe"

    def __init__(self, config: dict[str, Any]) -> None:
        self._settings = MediaPipeSettings.from_dict(config)
        self._face_landmarker: Any | None = None
        self._hand_landmarker: Any | None = None

    def _ensure_models(self) -> None:
        if self._face_landmarker is not None and self._hand_landmarker is not None:
            return
        from mediapipe.tasks import python as mp_python  # noqa: PLC0415
        from mediapipe.tasks.python import vision as mp_vision  # noqa: PLC0415

        face_model = Path(self._settings.face_model)
        hand_model = Path(self._settings.hand_model)
        if not face_model.exists() or not hand_model.exists():
            msg = (
                f"MediaPipe 模型缺失: {face_model} / {hand_model}，"
                "请运行 scripts/download_models.py"
            )
            raise FileNotFoundError(msg)

        logger.info("加载 MediaPipe 模型: {} / {}", face_model.name, hand_model.name)
        self._face_landmarker = mp_vision.FaceLandmarker.create_from_options(
            mp_vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(face_model)),
                num_faces=1,
            )
        )
        self._hand_landmarker = mp_vision.HandLandmarker.create_from_options(
            mp_vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(hand_model)),
                num_hands=self._settings.num_hands,
            )
        )

    def analyze(self, frame: Frame) -> PoseFeatures:
        """提取嘴部区域与手部关键点；模型异常时返回空特征（不中断管线）。"""
        import mediapipe as mp  # noqa: PLC0415

        try:
            self._ensure_models()
        except FileNotFoundError:
            logger.warning("MediaPipe 模型未就绪，跳过姿态分析")
            return PoseFeatures()

        rgb = frame.image[:, :, ::-1]
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb.copy())
        mouth_box = self._detect_mouth(mp_image, frame)
        hands = self._detect_hands(mp_image, frame)
        return PoseFeatures(mouth_box=mouth_box, hands=hands)

    def _detect_mouth(self, mp_image: Any, frame: Frame) -> Box | None:
        assert self._face_landmarker is not None
        result = self._face_landmarker.detect(mp_image)
        if not result.face_landmarks:
            return None
        landmarks = result.face_landmarks[0]
        xs = [landmarks[i].x * frame.width for i in _MOUTH_LANDMARKS]
        ys = [landmarks[i].y * frame.height for i in _MOUTH_LANDMARKS]
        return Box(min(xs), min(ys), max(xs), max(ys))

    def _detect_hands(self, mp_image: Any, frame: Frame) -> list[HandFeatures]:
        assert self._hand_landmarker is not None
        result = self._hand_landmarker.detect(mp_image)
        hands: list[HandFeatures] = []
        for i, landmarks in enumerate(result.hand_landmarks):
            handedness = "unknown"
            confidence = 0.0
            if result.handedness and i < len(result.handedness):
                category = result.handedness[i][0]
                handedness = str(category.category_name)
                confidence = float(category.score)
            hands.append(
                HandFeatures(
                    wrist=_to_px(landmarks, HAND_WRIST, frame.width, frame.height),
                    thumb_tip=_to_px(landmarks, HAND_THUMB_TIP, frame.width, frame.height),
                    index_tip=_to_px(landmarks, HAND_INDEX_TIP, frame.width, frame.height),
                    middle_tip=_to_px(landmarks, HAND_MIDDLE_TIP, frame.width, frame.height),
                    handedness=handedness,
                    confidence=confidence,
                )
            )
        return hands

    def close(self) -> None:
        if self._face_landmarker is not None:
            self._face_landmarker.close()
            self._face_landmarker = None
        if self._hand_landmarker is not None:
            self._hand_landmarker.close()
            self._hand_landmarker = None
