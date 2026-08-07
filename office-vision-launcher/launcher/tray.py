"""托盘界面：pystray 图标 + 菜单，状态图标随 Agent 运行情况变色。"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import webbrowser
from enum import Enum, auto

import pystray
from PIL import Image, ImageDraw

from . import updater
from .config import AppConfig, config_path
from .services import ServiceManager


class UpdateState(Enum):
    IDLE = auto()        # 显示当前版本，点击检查
    CHECKING = auto()
    AVAILABLE = auto()   # 发现新版本，点击安装
    DOWNLOADING = auto()
    UP_TO_DATE = auto()  # 短暂展示后回到 IDLE
    ERROR = auto()


_COLOR_RUNNING = (34, 197, 94)     # 绿：Agent 运行中
_COLOR_STOPPED = (148, 163, 184)   # 灰：已停止
_COLOR_FAILED = (239, 68, 68)      # 红：崩溃熔断
_COLOR_UPDATING = (59, 130, 246)   # 蓝：升级进行中

_APP_NAME = "Office Vision Agent"


def _make_icon(color: tuple[int, int, int]) -> Image.Image:
    """绘制纯色圆点图标（64x64，托盘会自动缩放）。"""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=color + (255,))
    return img


class TrayApp:
    def __init__(self, config: AppConfig, manager: ServiceManager):
        self.config = config
        self.manager = manager
        self.update_state = UpdateState.IDLE
        self.update_message = ""  # 错误提示 / 新版本号
        self._pending_release: updater.Release | None = None
        self._lock = threading.Lock()

        self.icon = pystray.Icon(
            _APP_NAME,
            _make_icon(_COLOR_STOPPED),
            _APP_NAME,
            self._build_menu(),
        )

    # ---- 菜单 ----

    def _build_menu(self) -> pystray.Menu:
        items: list = []
        for name, svc in self.manager.services.items():
            items.append(
                pystray.MenuItem(
                    lambda item, name=name, svc=svc: self._service_title(name, svc),
                    self._toggle_service(name),
                )
            )
        items.append(
            pystray.MenuItem(
                lambda item: f"服务地址：{self.config.server_url}（点击修改）",
                self._open_config_file,
            )
        )
        items.append(pystray.MenuItem("打开 Dashboard", self._open_dashboard))
        items.append(pystray.Menu.SEPARATOR)
        items.append(pystray.MenuItem(lambda item: self._update_title(), self._on_update_clicked))
        items.append(pystray.MenuItem("退出", self._quit))
        return pystray.Menu(*items)

    def _service_title(self, name: str, svc) -> str:
        if self.manager.running(name):
            state = "运行中 ●"
            if self.manager.reachable(name):
                state = "运行中 ●（端口正常）"
            return f"{svc.spec.label}：{state}，点击停止"
        if svc.failed:
            if svc.reason:
                return f"{svc.spec.label}：启动失败 ✖（{svc.reason}），点击重试"
            return f"{svc.spec.label}：启动失败 ✖，点击重试"
        return f"{svc.spec.label}：已停止，点击启动"

    def _toggle_service(self, name: str):
        def action(_icon, _item):
            threading.Thread(target=self._do_toggle, args=(name,), daemon=True).start()

        return action

    def _do_toggle(self, name: str) -> None:
        if self.manager.running(name):
            self.manager.stop(name)
        else:
            self.manager.start(name)

    def _open_dashboard(self, _icon, _item) -> None:
        webbrowser.open(self.config.dashboard_url)

    def _open_config_file(self, _icon, _item) -> None:
        """打开 config.yaml 供用户修改服务地址等配置，保存后重启应用生效。"""
        path = str(config_path())
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform == "win32":
            os.startfile(path)  # Windows 专属 API，以默认编辑器打开
        else:
            subprocess.Popen(["xdg-open", path])

    # ---- 升级 ----

    def _update_title(self) -> str:
        with self._lock:
            state, message = self.update_state, self.update_message
        if state is UpdateState.CHECKING:
            return "正在检查更新…"
        if state is UpdateState.DOWNLOADING:
            return "正在下载更新…"
        if state is UpdateState.AVAILABLE:
            return f"发现新版本 {message}，点击安装"
        if state is UpdateState.UP_TO_DATE:
            return f"已是最新版本 v{updater.current_version()}"
        if state is UpdateState.ERROR:
            return f"更新检查失败：{message}"
        return f"检查更新（当前 v{updater.current_version()}）"

    def _on_update_clicked(self, _icon, _item) -> None:
        with self._lock:
            state = self.update_state
        if state in (UpdateState.CHECKING, UpdateState.DOWNLOADING):
            return
        if state is UpdateState.AVAILABLE and self._pending_release is not None:
            threading.Thread(target=self._install_update, daemon=True).start()
        else:
            threading.Thread(target=self._check_update, daemon=True).start()

    def _set_update_state(self, state: UpdateState, message: str = "") -> None:
        with self._lock:
            self.update_state = state
            self.update_message = message

    def _check_update(self) -> None:
        self._set_update_state(UpdateState.CHECKING)
        try:
            release = updater.fetch_latest_release(
                self.config.github_repo, self.config.github_token, self.config.asset_pattern
            )
        except updater.UpdateError as exc:
            self._set_update_state(UpdateState.ERROR, str(exc))
            return
        if release is None:
            self._set_update_state(UpdateState.ERROR, "仓库尚无 Release")
            return
        if not updater.has_update(release):
            self._set_update_state(UpdateState.UP_TO_DATE)
            threading.Timer(8.0, lambda: self._set_update_state(UpdateState.IDLE)).start()
            return
        self._pending_release = release
        self._set_update_state(UpdateState.AVAILABLE, release.tag)

    def _install_update(self) -> None:
        release = self._pending_release
        if release is None:
            return
        self._set_update_state(UpdateState.DOWNLOADING)
        try:
            asset = updater.download_asset(release, self.config.github_token)
            updater.apply_update(asset)
        except updater.UpdateError as exc:
            self._set_update_state(UpdateState.ERROR, str(exc))
            return
        # 自替换脚本已接管：停掉受管服务后退出，外部脚本会拉起新版本
        self.manager.stop_all()
        self.icon.stop()

    # ---- 状态刷新 ----

    def _status_loop(self) -> None:
        """每 2 秒刷新托盘图标颜色与提示文案。"""
        while True:
            color = _COLOR_STOPPED
            title = f"{_APP_NAME}：已停止"
            with self._lock:
                updating = self.update_state in (UpdateState.CHECKING, UpdateState.DOWNLOADING)
            if updating:
                color, title = _COLOR_UPDATING, f"{_APP_NAME}：升级中…"
            else:
                failed = any(svc.failed for svc in self.manager.services.values())
                if self.manager.all_running():
                    color = _COLOR_FAILED if failed else _COLOR_RUNNING
                    title = f"{_APP_NAME}：运行中"
                elif failed:
                    color, title = _COLOR_FAILED, f"{_APP_NAME}：启动失败，请查看日志"
            self.icon.icon = _make_icon(color)
            self.icon.title = title
            try:
                self.icon.update()
            except Exception:  # 某些平台退出时 update 会抛错，忽略
                return
            threading.Event().wait(2.0)

    def _quit(self, _icon, _item) -> None:
        self.manager.stop_all()
        self.icon.stop()

    def run(self) -> None:
        threading.Thread(target=self._status_loop, daemon=True).start()
        self.manager.start_all()  # 应用启动即拉起 Agent
        self.icon.run()  # 阻塞主线程（macOS 要求事件循环在主线程）
