"""部署日志上传：首次部署完成/失败后把过程记录上报 Server。

初次安装阶段 Agent 尚未部署，其进程内日志上传器无从运行，
部署失败时的日志是远程排查的唯一线索，因此这里独立实现一份
同步上报（部署线程本就是后台线程，无异步需求）。

尽力而为：任何上传失败只写本地日志，不影响部署结果与托盘状态。
请求体与 Agent 的 LogUploader 同构（POST /api/logs，chunk_id 幂等），
component 固定 "launcher"；trigger 用 "deploy"（成功）/"error"（失败），
Dashboard 按 error 红色徽标区分。
"""

from __future__ import annotations

import platform
import socket
import uuid
from datetime import UTC, datetime
from pathlib import Path

import requests
import yaml

from . import __version__

_TIMEOUT_SECONDS = 10.0


def _read_device_id(agent_workdir: Path) -> str:
    """优先 agent.yaml 的 agent.device_id（与 Agent 上报身份一致）；
    克隆前失败时文件尚不存在，回退主机名标识设备。"""
    agent_yaml = agent_workdir / "config" / "agent.yaml"
    try:
        raw = yaml.safe_load(agent_yaml.read_text(encoding="utf-8")) or {}
        device_id = str((raw.get("agent") or {}).get("device_id") or "")
        if device_id:
            return device_id
    except (OSError, yaml.YAMLError):
        pass
    return socket.gethostname()


def deploy_header(repo: str) -> str:
    """部署记录首行：托盘版本与设备环境，便于 Server 侧归类。"""
    return (
        f"托盘 v{__version__} | {platform.system()} {platform.release()} | "
        f"python {platform.python_version()} | repo={repo}"
    )


def upload_deploy_log(
    server_url: str,
    agent_workdir: Path,
    lines: list[str],
    *,
    success: bool,
) -> bool:
    """上报部署过程记录；返回 Server 是否受理（200）。

    best-effort：吞掉全部异常——日志通道不能反过来影响部署流程。
    """
    if not server_url or not lines:
        return False
    payload = {
        "chunk_id": uuid.uuid4().hex,
        "device_id": _read_device_id(agent_workdir),
        "component": "launcher",
        "trigger": "deploy" if success else "error",
        "logged_at": datetime.now(UTC).isoformat(),
        "content": "".join(lines),
    }
    try:
        resp = requests.post(
            f"{server_url.rstrip('/')}/api/logs", json=payload, timeout=_TIMEOUT_SECONDS
        )
        return resp.status_code == 200
    except requests.RequestException:
        return False
