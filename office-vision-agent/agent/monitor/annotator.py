"""Overlay 标注器：在画面上绘制全部可视化调试图层。

图层（均可单独开关）：
- Bounding Box   所有 Detector 统一绘制（Person / Face / Cup / Phone / Cigarette...）
- Face           面部关键点嘴部区域框
- Mouth          FaceMesh 嘴部区域
- Hand           MediaPipe Hand Landmark 骨架
- Distance       手→嘴连线与像素距离
- State / FPS / Event   文字信息

新 Detector 产出的 Detection 会自动绘制，无需修改本模块。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields

import cv2
import numpy as np
import numpy.typing as npt

from agent.vision.frame import Box, PoseFeatures, VisionContext

# MediaPipe HandLandmarker 骨架连接
_HAND_CONNECTIONS = (
    (0, 1),
    (1, 2),
    (2, 3),
    (3, 4),
    (0, 5),
    (5, 6),
    (6, 7),
    (7, 8),
    (5, 9),
    (9, 10),
    (10, 11),
    (11, 12),
    (9, 13),
    (13, 14),
    (14, 15),
    (15, 16),
    (13, 17),
    (17, 18),
    (18, 19),
    (19, 20),
    (0, 17),
)

_LABEL_COLORS: dict[str, tuple[int, int, int]] = {
    "person": (0, 200, 0),
    "face": (255, 160, 0),
    "hand": (0, 200, 255),
    "cup": (255, 0, 200),
    "phone": (180, 180, 0),
    "cigarette": (0, 0, 255),
}
_DEFAULT_COLOR = (200, 200, 200)


@dataclass
class OverlayToggles:
    """Overlay 开关（Dashboard 可实时修改）。"""

    face: bool = True
    hand: bool = True
    mouth: bool = True
    bbox: bool = True
    state: bool = True
    fps: bool = True
    event: bool = True
    distance: bool = True

    def update(self, changes: dict[str, bool]) -> None:
        valid = {f.name for f in fields(self)}
        for key, value in changes.items():
            if key in valid:
                setattr(self, key, bool(value))

    def as_dict(self) -> dict[str, bool]:
        return {f.name: bool(getattr(self, f.name)) for f in fields(self)}


def mouth_center(mouth_box: Box) -> tuple[float, float]:
    return ((mouth_box.x1 + mouth_box.x2) / 2, (mouth_box.y1 + mouth_box.y2) / 2)


def hand_mouth_distance(
    pose: PoseFeatures,
) -> tuple[float, tuple[float, float], tuple[float, float]] | None:
    """最近的指尖到嘴部中心的像素距离；无脸或无手返回 None。"""
    if pose.mouth_box is None or not pose.hands:
        return None
    cx, cy = mouth_center(pose.mouth_box)
    best: tuple[float, tuple[float, float], tuple[float, float]] | None = None
    for hand in pose.hands:
        for tip in hand.fingertips:
            dist = math.hypot(tip[0] - cx, tip[1] - cy)
            if best is None or dist < best[0]:
                best = (dist, tip, (cx, cy))
    return best


def annotate(
    image: npt.NDArray[np.uint8],
    context: VisionContext,
    toggles: OverlayToggles,
    state_text: str = "",
    fps_text: str = "",
    event_text: str = "",
) -> npt.NDArray[np.uint8]:
    """在画面副本上绘制全部启用的 Overlay，返回新图。"""
    canvas = image.copy()
    pose = context.pose

    if toggles.bbox:
        for det in context.detections:
            color = _LABEL_COLORS.get(det.label, _DEFAULT_COLOR)
            x1, y1, x2, y2 = det.box.as_int_tuple()
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
            label = f"{det.label} {det.confidence:.2f}"
            cv2.putText(
                canvas, label, (x1, max(y1 - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1
            )

    if toggles.mouth and pose.mouth_box is not None:
        x1, y1, x2, y2 = pose.mouth_box.as_int_tuple()
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 120, 255), 1)
        cv2.putText(
            canvas, "mouth", (x1, max(y1 - 4, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 120, 255), 1
        )

    if toggles.hand:
        for hand in pose.hands:
            pts = _hand_points(hand)
            for a, b in _HAND_CONNECTIONS:
                if a < len(pts) and b < len(pts):
                    cv2.line(canvas, pts[a], pts[b], (0, 200, 255), 1)
            for tip in hand.fingertips:
                cv2.circle(canvas, (int(tip[0]), int(tip[1])), 3, (0, 0, 255), -1)

    if toggles.distance:
        measured = hand_mouth_distance(pose)
        if measured is not None:
            dist, tip, center = measured
            cv2.line(
                canvas,
                (int(tip[0]), int(tip[1])),
                (int(center[0]), int(center[1])),
                (255, 255, 0),
                1,
            )
            mid = ((tip[0] + center[0]) / 2, (tip[1] + center[1]) / 2)
            cv2.putText(
                canvas,
                f"Distance: {dist:.0f} px",
                (int(mid[0]) + 6, int(mid[1])),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 0),
                1,
            )

    if toggles.face and pose.mouth_box is not None:
        # FaceLandmarker 仅暴露嘴部区域，用外扩框近似面部位置
        fx1, fy1, fx2, fy2 = pose.mouth_box.expand(3.0).as_int_tuple()
        cv2.rectangle(canvas, (fx1, fy1), (fx2, fy2), (255, 160, 0), 1)
        cv2.putText(
            canvas, "face", (fx1, max(fy1 - 4, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 160, 0), 1
        )

    row = 20
    if toggles.state and state_text:
        cv2.putText(canvas, state_text, (10, row), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        row += 24
    if toggles.fps and fps_text:
        cv2.putText(canvas, fps_text, (10, row), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        row += 20
    if toggles.event and event_text:
        cv2.putText(canvas, event_text, (10, row), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (80, 200, 255), 1)
    return canvas


def _hand_points(hand: object) -> list[tuple[int, int]]:
    """手部 21 关键点不可得时，用已有特征点近似骨架（调试用途）。"""
    from agent.vision.frame import HandFeatures  # noqa: PLC0415

    assert isinstance(hand, HandFeatures)
    wrist = hand.wrist
    pts: list[tuple[int, int]] = []
    # 索引与 _HAND_CONNECTIONS 对齐：0 wrist, 4/8/12 为指尖近似
    tips = [hand.thumb_tip, hand.index_tip, hand.middle_tip]
    for i in range(21):
        if i == 0:
            pts.append((int(wrist[0]), int(wrist[1])))
        elif i in (4, 8, 12):
            tip = tips[[4, 8, 12].index(i)]
            pts.append((int(tip[0]), int(tip[1])))
        else:  # 中间关节：手腕与指尖连线插值
            anchor = tips[min(i // 4, 2)] if i < 13 else tips[2]
            t = (i % 4) / 4 if i < 13 else 0.5
            pts.append(
                (
                    int(wrist[0] + (anchor[0] - wrist[0]) * t),
                    int(wrist[1] + (anchor[1] - wrist[1]) * t),
                )
            )
    return pts
