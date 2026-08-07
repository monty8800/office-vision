"""受管服务生命周期：启动/停止、看门狗自动重启、端口探活、日志落盘、服务地址同步。"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from .config import ServiceSpec

_IS_WINDOWS = sys.platform == "win32"

# GUI 启动时 PATH 不完整（无 shell profile），为关键命令补充候选路径
_FALLBACK_DIRS: tuple[str, ...] = (
    (
        os.path.expanduser("~/.local/bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
    )
    if not _IS_WINDOWS
    else (
        os.path.expandvars(r"%USERPROFILE%\.local\bin"),
        os.path.expandvars(r"%APPDATA%\npm"),
        os.path.expandvars(r"%ProgramFiles%\nodejs"),
    )
)

# 连续快速崩溃超过该次数则放弃自动重启，避免死循环刷日志
_MAX_CRASH_LOOP = 5
_CRASH_WINDOW_SECONDS = 10.0


def _resolve_executable(name: str) -> str:
    """解析可执行文件路径：PATH 优先，其次平台候选目录。"""
    found = shutil.which(name)
    if found:
        return found
    exts = ("", ".cmd", ".exe") if _IS_WINDOWS else ("",)
    for directory in _FALLBACK_DIRS:
        for ext in exts:
            candidate = Path(directory) / f"{name}{ext}"
            if candidate.is_file():
                return str(candidate)
    return name  # 交给系统报错，日志里可见原因


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _kill_tree(pid: int) -> None:
    """终止进程及其所有子进程（uv/npm 会派生子进程）。"""
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    children = parent.children(recursive=True)
    for proc in children + [parent]:
        proc.terminate()
    _, alive = psutil.wait_procs(children + [parent], timeout=5)
    for proc in alive:
        proc.kill()


def _sync_server_url(agent_yaml: Path, server_url: str) -> bool:
    """把服务地址写入 agent.yaml 的 server.url（保留注释与格式，仅改目标行）。

    Agent 配置以 YAML 为唯一源（第四原则），托盘应用作为部署入口代为写入，
    避免引入环境变量隐式覆盖。
    """
    lines = agent_yaml.read_text(encoding="utf-8").splitlines(keepends=True)
    in_server = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.fullmatch(r"server:\s*(#.*)?", stripped):
            in_server = True
            continue
        if in_server:
            if stripped and not line[0].isspace():
                break  # 离开 server 段
            match = re.match(r"^(\s+)url:\s", line)
            if match:
                new_line = f'{match.group(1)}url: "{server_url}"\n'
                if new_line == line:
                    return False
                lines[i] = new_line
                agent_yaml.write_text("".join(lines), encoding="utf-8")
                return True
    return False


@dataclass
class ManagedService:
    spec: ServiceSpec
    log_dir: Path
    proc: subprocess.Popen | None = None
    stop_flag: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    crash_count: int = 0
    failed: bool = False

    @property
    def log_file(self) -> Path:
        return self.log_dir / f"{self.spec.name}.log"


class ServiceManager:
    """按配置托管服务：start 后由看门狗线程保证进程存活，stop 时彻底终止进程树。"""

    def __init__(
        self,
        specs: list[ServiceSpec],
        restart_delay: float,
        log_dir: Path,
        server_url: str = "",
    ):
        self.restart_delay = restart_delay
        self.server_url = server_url
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.services: dict[str, ManagedService] = {
            spec.name: ManagedService(spec=spec, log_dir=log_dir) for spec in specs
        }

    # ---- 状态查询 ----

    def running(self, name: str) -> bool:
        svc = self.services[name]
        return svc.proc is not None and svc.proc.poll() is None

    def reachable(self, name: str) -> bool:
        return _port_open(self.services[name].spec.port)

    def all_running(self) -> bool:
        return all(self.running(name) for name in self.services)

    # ---- 生命周期 ----

    def start(self, name: str) -> None:
        svc = self.services[name]
        if self.running(name):
            return
        self._sync_agent_config(svc)
        svc.stop_flag.clear()
        svc.failed = False
        svc.crash_count = 0
        svc.thread = threading.Thread(
            target=self._supervise, args=(svc,), name=f"watchdog-{name}", daemon=True
        )
        svc.thread.start()

    def stop(self, name: str) -> None:
        svc = self.services[name]
        svc.stop_flag.set()
        if svc.proc is not None:
            _kill_tree(svc.proc.pid)
        if svc.thread is not None and svc.thread is not threading.current_thread():
            svc.thread.join(timeout=8)

    def start_all(self) -> None:
        for name in self.services:
            self.start(name)

    def stop_all(self) -> None:
        for name in self.services:
            self.stop(name)

    # ---- 内部 ----

    def _sync_agent_config(self, svc: ManagedService) -> None:
        """启动前把托盘应用配置的服务地址同步到 agent.yaml（仅存在时生效）。"""
        if not self.server_url:
            return
        agent_yaml = svc.spec.workdir / "config" / "agent.yaml"
        if not agent_yaml.is_file():
            return
        try:
            if _sync_server_url(agent_yaml, self.server_url):
                self._append_log(svc, f"已同步服务地址到 agent.yaml：{self.server_url}\n")
        except OSError as exc:
            self._append_log(svc, f"同步服务地址失败：{exc}\n")

    def _spawn(self, svc: ManagedService) -> subprocess.Popen:
        spec = svc.spec
        command = [_resolve_executable(spec.command[0]), *spec.command[1:]]
        kwargs: dict = {
            "cwd": str(spec.workdir),
            "stdout": open(svc.log_file, "ab", buffering=0),  # 子进程持有句柄，不可用上下文管理器
            "stderr": subprocess.STDOUT,
        }
        if _IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return subprocess.Popen(command, **kwargs)

    def _supervise(self, svc: ManagedService) -> None:
        """服务包循环：进程退出后按 restart_delay 自动拉起，连续快速崩溃则熔断。"""
        while not svc.stop_flag.is_set():
            started = time.monotonic()
            try:
                svc.proc = self._spawn(svc)
            except OSError as exc:
                self._append_log(svc, f"启动失败：{exc}\n")
                svc.failed = True
                return
            code = svc.proc.wait()
            svc.proc = None
            if svc.stop_flag.is_set():
                break
            uptime = time.monotonic() - started
            if uptime > _CRASH_WINDOW_SECONDS:
                svc.crash_count = 0  # 稳定运行过，重置崩溃计数
            else:
                svc.crash_count += 1
                if svc.crash_count >= _MAX_CRASH_LOOP:
                    self._append_log(svc, f"连续 {svc.crash_count} 次快速崩溃，停止自动重启\n")
                    svc.failed = True
                    return
            self._append_log(
                svc, f"进程退出（code={code}），{self.restart_delay:.0f} 秒后自动重启\n"
            )
            svc.stop_flag.wait(self.restart_delay)

    def _append_log(self, svc: ManagedService, message: str) -> None:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(svc.log_file, "a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] [launcher] {message}")
