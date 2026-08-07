"""托盘应用入口：python -m launcher 或打包后的可执行文件。"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if sys.platform == "win32":
        # Windows 任务栏/托盘按 AppUserModelID 归组
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OfficeVision.Tray")

    from .config import load_config
    from .services import ServiceManager
    from .tray import TrayApp

    try:
        config = load_config()
    except FileNotFoundError as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        sys.exit(1)

    log_dir = Path(__file__).resolve().parent.parent / "data" / "logs"
    if getattr(sys, "frozen", False):
        # 打包模式：日志放在可执行文件旁（.app 则放其所在目录）
        exe = Path(sys.executable)
        base = exe.parent.parent.parent if sys.platform == "darwin" else exe.parent
        log_dir = base / "data" / "logs"

    manager = ServiceManager(config.services, config.restart_delay_seconds, log_dir)
    TrayApp(config, manager).run()


if __name__ == "__main__":
    main()
