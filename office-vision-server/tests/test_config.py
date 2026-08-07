"""Server 配置系统测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from server.core.config import _normalize_database_url, load_config


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


class TestDatabaseUrlNormalize:
    """PaaS 注入的裸 postgres 连接串自动补 asyncpg 驱动。"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (
                "postgres://u:p@host:5432/db",
                "postgresql+asyncpg://u:p@host:5432/db",
            ),
            (
                "postgresql://u:p@host:5432/db",
                "postgresql+asyncpg://u:p@host:5432/db",
            ),
        ],
    )
    def test_裸连接串补驱动(self, raw: str, expected: str) -> None:
        assert _normalize_database_url(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "sqlite+aiosqlite:///data/office_vision.db",
            "postgresql+asyncpg://u:p@host:5432/db",
        ],
    )
    def test_已带驱动或sqlite原样保留(self, raw: str) -> None:
        assert _normalize_database_url(raw) == raw

    def test_环境变量注入后归一化(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OVA_DATABASE_URL", "postgresql://u:p@host:5432/db")
        assert load_config().database_url == "postgresql+asyncpg://u:p@host:5432/db"
