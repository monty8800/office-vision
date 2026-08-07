"""launcher.config 安装模式测试：用户配置目录下的 workdir 解析与首次生成标记。"""

from __future__ import annotations

from pathlib import Path

from launcher import config


def _write_config(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config.DEFAULT_CONFIG_YAML, encoding="utf-8")


def test_install_mode_resolves_workdir_under_repo(tmp_path: Path, monkeypatch: object) -> None:
    """安装模式：配置在用户目录，workdir 解析到 用户目录/office-vision/office-vision-agent。"""
    support = tmp_path / "support"
    _write_config(support / "config.yaml")
    monkeypatch.setattr(config, "app_support_dir", lambda: support)  # type: ignore[attr-defined]
    monkeypatch.setattr(config, "config_path", lambda: support / "config.yaml")  # type: ignore[attr-defined]

    cfg = config.load_config()
    agent = cfg.services[0]
    assert agent.workdir == (support / "office-vision" / "office-vision-agent").resolve()


def test_portable_mode_workdir_relative_to_config(tmp_path: Path, monkeypatch: object) -> None:
    """便携模式：配置在部署目录，workdir 按 ../office-vision-agent 相对解析（旧行为不变）。"""
    deploy = tmp_path / "deploy-tray"
    _write_config(deploy / "config.yaml")
    monkeypatch.setattr(config, "app_support_dir", lambda: tmp_path / "support")  # type: ignore[attr-defined]
    monkeypatch.setattr(config, "config_path", lambda: deploy / "config.yaml")  # type: ignore[attr-defined]

    cfg = config.load_config()
    agent = cfg.services[0]
    assert agent.workdir == (tmp_path / "office-vision-agent").resolve()


def test_config_just_created_flag(tmp_path: Path, monkeypatch: object) -> None:
    """自动生成配置后 config_just_created() 为真（首次安装引导依赖此标记）。"""
    support = tmp_path / "support"
    monkeypatch.setattr(config, "app_support_dir", lambda: support)  # type: ignore[attr-defined]
    monkeypatch.setattr(config, "_CONFIG_CREATED", None)  # type: ignore[attr-defined]

    assert not config.config_just_created()
    config._create_default_config()
    assert config.config_just_created()
    monkeypatch.setattr(config, "_CONFIG_CREATED", None)  # type: ignore[attr-defined]
