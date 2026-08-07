"""托盘应用入口：python -m launcher 或打包后的可执行文件。"""

from __future__ import annotations

import sys


def main() -> None:
    if sys.platform == "win32":
        # Windows 任务栏/托盘按 AppUserModelID 归组
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OfficeVision.Tray")

    from .config import app_base_dir, app_support_dir, load_config
    from .deploy import Deployer
    from .services import ServiceManager
    from .tray import TrayApp

    try:
        config = load_config()
    except FileNotFoundError as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        sys.exit(1)

    log_dir = app_base_dir() / "data" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # 部署目录不可写（如直接从 DMG 卷内运行）时回退到用户配置目录
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
