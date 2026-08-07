"""包级入口：供 PyInstaller 打包（保持包上下文，使相对导入可用）。"""

import os
import sys
import traceback
from pathlib import Path


def _crash_log_path() -> Path:
    """崩溃日志位置：部署目录的 data/logs/；不可写（如 DMG 卷内运行）时
    回退用户配置目录。"""
    exe = Path(sys.executable)
    base = exe.parent.parent.parent.parent if sys.platform == "darwin" else exe.parent
    log_dir = base / "data" / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / "crash.log"
    except OSError:
        fallback = (
            Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
            if sys.platform == "win32"
            else Path.home() / "Library" / "Application Support"
        ) / "Office Vision Tray" / "data" / "logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback / "crash.log"


if __name__ == "__main__":
    try:
        from launcher.main import main

        main()
    except BaseException:
        # 无控制台模式（--windowed）下 stderr 不可见，崩溃时落盘便于排查
        try:
            with _crash_log_path().open("a", encoding="utf-8") as fh:
                traceback.print_exc(file=fh)
        except OSError:
            pass
        raise
