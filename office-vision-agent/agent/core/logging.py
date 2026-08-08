"""Agent 日志（Loguru，级别来自配置文件）。

stderr sink 供终端/Launcher 重定向；可选文件 sink 供日志上传器
增量读取上报（见 transport/log_uploader.py）。
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan> - <level>{message}</level>"
)


def setup_logging(
    level: str = "INFO",
    log_file: str | Path | None = None,
    rotation: str = "10 MB",
    retention: int = 5,
) -> None:
    """统一日志格式；级别来自 agent.yaml 的 agent.log_level。

    log_file 非 None 时追加落盘 sink（自动轮转），供日志上传器读取。
    """
    logger.remove()
    logger.add(sys.stderr, level=level.upper(), format=_FORMAT)
    if log_file is not None:
        logger.add(
            log_file,
            level=level.upper(),
            format=_FORMAT,
            colorize=False,
            rotation=rotation,
            retention=retention,
        )
