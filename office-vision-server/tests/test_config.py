"""Server 配置系统测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from server.core.config import load_config


class TestLoadConfig:
    def test_默认配置加载(self) -> None:
        config = load_config()
        assert config.server.port == 8000
        assert config.database_url.startswith("sqlite+aiosqlite:///")
        assert config.events.dedup_window_seconds == 5
        assert config.automation.enabled is False
        assert config.users.default_user == "admin"

    def test_环境变量覆盖数据库(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OVA_DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        assert load_config().database_url == "sqlite+aiosqlite:///:memory:"

    def test_文件不存在报错(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="配置文件不存在"):
            load_config(tmp_path / "missing.yaml")

    def test_未知键忽略(self, tmp_path: Path) -> None:
        config_file = tmp_path / "server.yaml"
        config_file.write_text(
            "server:\n  port: 9000\n  future_key: true\ndatabase:\n  url: sqlite+aiosqlite://\n",
            encoding="utf-8",
        )
        config = load_config(config_file)
        assert config.server.port == 9000
        assert config.database_url == "sqlite+aiosqlite://"

    def test_格式错误报错(self, tmp_path: Path) -> None:
        config_file = tmp_path / "server.yaml"
        config_file.write_text("- 1\n- 2\n", encoding="utf-8")
        with pytest.raises(ValueError, match="格式错误"):
            load_config(config_file)
