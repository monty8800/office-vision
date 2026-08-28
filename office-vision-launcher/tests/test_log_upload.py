"""launcher.log_upload 测试：设备标识解析、payload 构造、失败容错与部署流程集成。"""

from __future__ import annotations

from pathlib import Path

import pytest
import requests

from launcher import log_upload, services
from launcher.config import ServiceSpec
from launcher.deploy import DeployError
from launcher.services import ServiceManager


def _write_agent_yaml(workdir: Path, device_id: str) -> None:
    (workdir / "config").mkdir(parents=True)
    (workdir / "config" / "agent.yaml").write_text(
        f"agent:\n  device_id: {device_id}\n", encoding="utf-8"
    )


class FakeResponse:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code


def test_device_id_prefers_agent_yaml(tmp_path: Path) -> None:
    """与 Agent 上报身份一致：优先 agent.yaml 的 device_id。"""
    workdir = tmp_path / "office-vision-agent"
    _write_agent_yaml(workdir, "meeting-room-1")
    assert log_upload._read_device_id(workdir) == "meeting-room-1"  # noqa: SLF001


def test_device_id_falls_back_to_hostname(tmp_path: Path) -> None:
    """克隆前失败时 agent.yaml 不存在，回退主机名标识设备。"""
    assert log_upload._read_device_id(tmp_path / "missing")  # noqa: SLF001


def test_upload_payload_and_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, json: dict, timeout: float) -> FakeResponse:  # noqa: A002
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse(200)

    monkeypatch.setattr(log_upload.requests, "post", fake_post)
    workdir = tmp_path / "office-vision-agent"
    _write_agent_yaml(workdir, "dev-01")

    ok = log_upload.upload_deploy_log(
        "http://server:8000/", workdir, ["第一行\n", "第二行\n"], success=False
    )
    assert ok is True
    assert captured["url"] == "http://server:8000/api/logs"
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["device_id"] == "dev-01"
    assert payload["component"] == "launcher"
    assert payload["trigger"] == "error"
    assert payload["content"] == "第一行\n第二行\n"
    assert len(payload["chunk_id"]) == 32  # uuid4 hex，幂等键


def test_upload_success_trigger_is_deploy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, json: dict, timeout: float) -> FakeResponse:  # noqa: A002
        captured["json"] = json
        return FakeResponse(200)

    monkeypatch.setattr(log_upload.requests, "post", fake_post)
    ok = log_upload.upload_deploy_log(
        "http://server:8000", tmp_path, ["行\n"], success=True
    )
    assert ok is True
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["trigger"] == "deploy"


def test_upload_swallows_network_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """best-effort：网络异常不得影响部署流程。"""

    def failing_post(*args: object, **kwargs: object) -> None:
        raise requests.ConnectionError("server 不可达")

    monkeypatch.setattr(log_upload.requests, "post", failing_post)
    ok = log_upload.upload_deploy_log("http://server:8000", tmp_path, ["行\n"], success=False)
    assert ok is False


def test_upload_skips_when_no_server_or_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("不应发起请求")

    monkeypatch.setattr(log_upload.requests, "post", fail_if_called)
    assert log_upload.upload_deploy_log("", tmp_path, ["行\n"], success=False) is False
    assert log_upload.upload_deploy_log("http://s:8000", tmp_path, [], success=False) is False


def _make_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ServiceManager:
    workdir = tmp_path / "office-vision-agent"
    spec = ServiceSpec(
        name="agent",
        label="Agent",
        port=8100,
        workdir=workdir,
        command=("uv", "run", "python", "-m", "agent.main"),
    )
    manager = ServiceManager(
        [spec], 0.1, tmp_path / "logs", server_url="http://server:8000", deployer=None
    )
    monkeypatch.setattr(manager, "start", lambda name: None)  # 成功路径不真正拉起进程
    return manager


def test_run_deploy_failure_uploads_error_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """部署失败必须上报（trigger=error），transcript 含失败原因。"""
    manager = _make_manager(tmp_path, monkeypatch)

    class FailingDeployer:
        repo = "monty8800/office-vision"

        def run(self, on_step=None) -> None:
            on_step("克隆仓库（仅 Agent 目录）")
            raise DeployError("仓库为私有：请在 config.yaml 填写 github_token 后重试")

    manager.deployer = FailingDeployer()  # type: ignore[assignment]
    uploaded: dict[str, object] = {}

    def capture(server_url: str, workdir: Path, lines: list[str], *, success: bool) -> bool:
        uploaded.update(
            server_url=server_url, content="".join(lines), success=success
        )
        return True

    monkeypatch.setattr(services, "upload_deploy_log", capture)

    svc = manager.services["agent"]
    manager._run_deploy(svc)  # noqa: SLF001

    assert manager.deploy_state == "failed"
    assert uploaded["success"] is False
    content = uploaded["content"]
    assert isinstance(content, str)
    assert "克隆仓库" in content
    assert "自动部署失败：仓库为私有" in content
    assert content.startswith("托盘 v")  # 头部含版本与平台信息


def test_run_deploy_success_uploads_deploy_chunk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _make_manager(tmp_path, monkeypatch)

    class OkDeployer:
        repo = "monty8800/office-vision"

        def run(self, on_step=None) -> None:
            for label in ("检查 uv 环境", "安装依赖（约 1~3 分钟）"):
                on_step(label)

    manager.deployer = OkDeployer()  # type: ignore[assignment]
    uploaded: dict[str, object] = {}

    def capture(server_url: str, workdir: Path, lines: list[str], *, success: bool) -> bool:
        uploaded.update(content="".join(lines), success=success)
        return True

    monkeypatch.setattr(services, "upload_deploy_log", capture)

    manager._run_deploy(manager.services["agent"])  # noqa: SLF001

    assert manager.deploy_state == "idle"
    assert uploaded["success"] is True
    content = uploaded["content"]
    assert isinstance(content, str)
    assert "检查 uv 环境" in content
    assert "环境部署完成" in content
