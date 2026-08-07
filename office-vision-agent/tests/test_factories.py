"""硬件/AI 抽象工厂测试（Platform Agnostic + AI 可替换）。"""

from __future__ import annotations

import pytest

from agent.vision.camera.base import BaseCamera, create_camera
from agent.vision.camera.uvc import UvcCamera
from agent.vision.detector.base import (
    BaseDetector,
    BasePoseDetector,
    create_detector,
    create_pose_detector,
)
from agent.vision.detector.mediapipe_pose import MediaPipePoseDetector
from agent.vision.detector.yolo import YoloDetector


class TestCameraFactory:
    def test_uvc(self) -> None:
        camera = create_camera("uvc", {"index": 0})
        assert isinstance(camera, UvcCamera)
        assert isinstance(camera, BaseCamera)

    def test_未实现类型(self) -> None:
        with pytest.raises(NotImplementedError):
            create_camera("rtsp", {})

    def test_未知类型报错(self) -> None:
        with pytest.raises(ValueError, match="未知摄像头类型"):
            create_camera("webcam-2077", {})


class TestDetectorFactory:
    def test_yolo懒加载_构造不载入权重(self) -> None:
        detector = create_detector("yolo", {"weights": "models/yolo11n.pt"})
        assert isinstance(detector, YoloDetector)
        assert isinstance(detector, BaseDetector)

    def test_mediapipe_pose(self) -> None:
        pose = create_pose_detector("mediapipe", {})
        assert isinstance(pose, MediaPipePoseDetector)
        assert isinstance(pose, BasePoseDetector)

    def test_未实现引擎(self) -> None:
        with pytest.raises(NotImplementedError):
            create_detector("coreml", {})

    def test_未知类型报错(self) -> None:
        with pytest.raises(ValueError, match="未知检测器类型"):
            create_detector("magic", {})
