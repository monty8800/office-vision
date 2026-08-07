"""托盘应用入口：python -m launcher 或打包后的可执行文件。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _open_for_edit(path: Path) -> None:
    """用系统默认编辑器打开配置文件（首次安装引导修改 server_url）。"""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        pass  # 引导失败不影响主流程，菜单里随时可打开


def main() -> None:
    if sys.platform == "win32":
        # Windows 任务栏/托盘按 AppUserModelID 归组
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OfficeVision.Tray")

    from .config import app_support_dir, config_just_created, config_path, load_config
    from .deploy import Deployer
    from .services import ServiceManager
    from .tray import TrayApp

    try:
        config = load_config()
    except FileNotFoundError as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        sys.exit(1)

    # 首次安装运行：自动生成的配置需用户确认服务器地址，直接打开引导编辑
    if config_just_created():
        _open_for_edit(config_path())

    log_dir = config_path().parent / "data" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # 配置目录不可写时回退到用户配置目录
        log_dir = app_support_dir() / "data" / "logs"

    # 首次部署器：新设备上环境缺失时自动克隆仓库/装依赖/下模型（基于 agent 服务的 workdir）
    agent_spec = next(iter(config.services))
    deployer = Deployer(config.github_repo, config.github_token, agent_spec.workdir)
    manager = ServiceManager(
        config.services,
        config.restart_delay_seconds,
        log_dir,
        server_url=config.server_url,
        deployer=deployer,
    )
    TrayApp(config, manager).run()


if __name__ == "__main__":
    main()
