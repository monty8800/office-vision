"""launcher.deploy 测试：克隆地址构建、token 脱敏、就绪判定与部署编排。"""

from __future__ import annotations

from pathlib import Path

import pytest

from launcher import deploy
from launcher.deploy import Deployer, DeployError


def test_build_clone_url_without_token() -> None:
    assert deploy.build_clone_url("monty8800/office-vision", "") == (
        "https://github.com/monty8800/office-vision.git"
    )


def test_build_clone_url_with_token() -> None:
    url = deploy.build_clone_url("monty8800/office-vision", "TOKEN123")
    assert url == "https://x-access-token:TOKEN123@github.com/monty8800/office-vision.git"


def test_mask_url_hides_token() -> None:
    masked = deploy.mask_url("fatal: unable to access https://x-access-token:SECRET@github.com/a/b.git")
    assert "SECRET" not in masked
    assert "****@github.com/a/b.git" in masked


def test_mask_url_keeps_plain_text() -> None:
    assert deploy.mask_url("connection refused") == "connection refused"


def test_agent_deployed_requires_agent_yaml(tmp_path: Path) -> None:
    workdir = tmp_path / "office-vision-agent"
    assert not deploy.agent_deployed(workdir)
    (workdir / "config").mkdir(parents=True)
    (workdir / "config" / "agent.yaml").write_text("agent: {}", encoding="utf-8")
    assert deploy.agent_deployed(workdir)


def test_deployer_run_order_and_skip_clone_when_deployed(
    tmp_path: Path, monkeypatch: object
) -> None:
    """已部署环境：跳过克隆，按 uv→依赖→模型 顺序执行。"""
    workdir = tmp_path / "office-vision-agent"
    (workdir / "config").mkdir(parents=True)
    (workdir / "config" / "agent.yaml").write_text("agent: {}", encoding="utf-8")

    calls: list[str] = []
    monkeypatch.setattr(deploy, "_ensure_uv", lambda: "/usr/bin/uv")  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        deploy, "_clone_repo", lambda repo, token, root: calls.append("clone")
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        deploy, "_install_deps", lambda uv, wd: calls.append("deps")
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        deploy, "_download_models", lambda uv, wd: calls.append("models")
    )

    steps: list[str] = []
    Deployer("monty8800/office-vision", "", workdir).run(on_step=steps.append)
    assert calls == ["deps", "models"]
    assert steps[0] == "检查 uv 环境"
    assert "克隆仓库" not in steps


def test_deployer_clones_when_missing(tmp_path: Path, monkeypatch: object) -> None:
    workdir = tmp_path / "office-vision-agent"  # 不存在 → 需要克隆
    calls: list[str] = []
    monkeypatch.setattr(deploy, "_ensure_uv", lambda: "/usr/bin/uv")  # type: ignore[attr-defined]
    monkeypatch.setattr(  # type: ignore[attr-defined]
        deploy, "_clone_repo", lambda repo, token, root: calls.append("clone")
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        deploy, "_install_deps", lambda uv, wd: calls.append("deps")
    )
    monkeypatch.setattr(  # type: ignore[attr-defined]
        deploy, "_download_models", lambda uv, wd: calls.append("models")
    )

    Deployer("monty8800/office-vision", "", workdir).run()
    assert calls == ["clone", "deps", "models"]


def test_deploy_error_propagates(tmp_path: Path, monkeypatch: object) -> None:
    workdir = tmp_path / "office-vision-agent"

    def failing_deps(uv: str, wd: Path) -> None:
        raise DeployError("依赖安装失败：网络")

    monkeypatch.setattr(deploy, "_ensure_uv", lambda: "/usr/bin/uv")  # type: ignore[attr-defined]
    monkeypatch.setattr(deploy, "_install_deps", failing_deps)  # type: ignore[attr-defined]
    with pytest.raises(DeployError, match="依赖安装失败"):
        Deployer("monty8800/office-vision", "", workdir).run()
