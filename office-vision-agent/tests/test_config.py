"""Agent 配置系统测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.core.config import load_config


class TestLoadConfig:
    def test_默认配置加载(self) -> None:
        config = load_config()
        assert config.agent.device_id == "mac-main"
        assert config.camera_type == "uvc"
        assert config.detector_type == "yolo"
        assert config.pose_type == "mediapipe"
        assert config.pipeline.process_fps == 10.0
        assert config.presence.sleep_after_seconds == 300
        assert config.monitor.enabled is True
        assert config.monitor.port == 8100

    def test_工厂所需原始段保留(self) -> None:
        config = load_config()
        assert config.camera["index"] == 0
        assert config.detector["person_only"] is True
        assert "face_model" in config.pose

    def test_环境变量覆盖路径(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        config_file = tmp_path / "agent.yaml"
        config_file.write_text("agent:\n  device_id: pi-01\n", encoding="utf-8")
        monkeypatch.setenv("OVA_AGENT_CONFIG", str(config_file))
        assert load_config().agent.device_id == "pi-01"

    def test_未知键忽略_缺失段落用默认(self, tmp_path: Path) -> None:
        config_file = tmp_path / "agent.yaml"
        config_file.write_text("agent:\n  device_id: test\n  future: 1\n", encoding="utf-8")
        config = load_config(config_file)
        assert config.agent.device_id == "test"
        assert config.pipeline.process_fps == 10.0
        assert config.monitor.enabled is False  # MonitorSettings 默认关闭

    def test_文件不存在报错(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="配置文件不存在"):
            load_config(tmp_path / "missing.yaml")

    def test_非映射格式报错(self, tmp_path: Path) -> None:
        config_file = tmp_path / "agent.yaml"
        config_file.write_text("- 1\n- 2\n", encoding="utf-8")
        with pytest.raises(ValueError, match="格式错误"):
            load_config(config_file)

    def test_段落类型错误报错(self, tmp_path: Path) -> None:
        config_file = tmp_path / "agent.yaml"
        config_file.write_text("camera: not-a-mapping\n", encoding="utf-8")
        with pytest.raises(ValueError, match="必须是映射"):
            load_config(config_file)
