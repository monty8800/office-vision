"""Agent 装配入口：配置 → 工厂 → EventBus → 管线 → 推送器（→ Debug Center）。

装配顺序即架构：
1. load_config（唯一配置源 agent.yaml）
2. EventBus + PresenceManager + PluginManager（事件驱动，第六原则）
3. Camera / Detector / Pose 全部经工厂创建（第三/五原则）
4. 实时监控仅在 debug.enabled 时装配，frame_tap 注入管线（独立模块）
5. EventPusher：事件 → 本地离线队列 → HTTP 批量上报（第一原则，Agent 不碰数据库）

运行：`uv run python -m agent.main` 或 `uv run agent`（见 pyproject scripts）。
"""

from __future__ import annotations

import asyncio
import signal
from pathlib import Path

import uvicorn
from loguru import logger

from agent.core.config import AgentConfig, load_config
from agent.core.logging import setup_logging
from agent.debug.api import create_debug_app
from agent.debug.hub import DebugHub
from agent.events.bus import EventBus
from agent.plugins.manager import PluginManager
from agent.presence.manager import PresenceManager
from agent.transport.http_publisher import HttpPublisher
from agent.transport.offline_store import OfflineStore
from agent.transport.pusher import EventPusher
from agent.vision.camera.base import create_camera
from agent.vision.detector.base import create_detector, create_pose_detector
from agent.vision.pipeline import VisionPipeline

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _build_debug_hub(config: AgentConfig, bus: EventBus, plugins: PluginManager) -> DebugHub | None:
    """debug.enabled=false 时返回 None，管线不注入钩子，生产零开销。"""
    if not config.debug.enabled:
        logger.info("实时监控已关闭（debug.enabled=false）")
        return None
    hub = DebugHub(config.agent.device_id, config.debug, bus)
    hub.register_plugins(plugins.names, plugins.debug_infos)  # 新插件自动出现在监控页
    logger.info("实时监控已启用（端口 {}）", config.debug.port)
    return hub


async def _serve_debug(hub: DebugHub) -> None:
    """Debug HTTP 服务与主循环同 loop 运行。"""
    server = uvicorn.Server(
        uvicorn.Config(
            create_debug_app(hub),
            host="127.0.0.1",
            port=hub.settings.port,
            log_level="warning",
        )
    )
    await server.serve()


async def _run(config: AgentConfig) -> None:
    bus = EventBus()

    # ---- 行为插件（插件化，第二原则） ----
    plugins = PluginManager(PROJECT_ROOT / config.plugins.dir, config.agent.device_id)
    plugins.load_all()

    presence = PresenceManager(config.agent.device_id, config.presence)
    debug_hub = _build_debug_hub(config, bus, plugins)

    # ---- 硬件与 AI（工厂创建，可替换） ----
    camera = create_camera(config.camera_type, config.camera)
    detector = create_detector(config.detector_type, config.detector)
    pose = create_pose_detector(config.pose_type, config.pose)

    pipeline = VisionPipeline(
        camera,
        detector,
        pose,
        presence,
        plugins,
        bus,
        process_fps=config.pipeline.process_fps,
        sleep_fps=config.pipeline.sleep_fps,
        frame_tap=debug_hub.on_frame if debug_hub else None,
    )

    pusher = EventPusher(
        HttpPublisher(config.server.url),
        OfflineStore(PROJECT_ROOT / config.server.offline_cache),
        bus,
        push_interval_seconds=config.server.push_interval_seconds,
    )

    # ---- 启动（监控服务先于摄像头：便于诊断硬件/权限问题） ----
    await pusher.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    tasks: list[asyncio.Task[None]] = [
        asyncio.create_task(pusher.run(), name="pusher"),
    ]
    if debug_hub:
        tasks.append(asyncio.create_task(_serve_debug(debug_hub), name="debug-http"))

    if pipeline.open():
        tasks.append(asyncio.create_task(pipeline.run(), name="pipeline"))
        logger.info("{} 启动完成（device={}）", config.agent.name, config.agent.device_id)
    else:
        logger.error("摄像头打开失败（检查系统权限/设备号）；管线未启动，等待手动停止")
    await stop.wait()

    # ---- 优雅停止 ----
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    pipeline.shutdown()
    await pusher.stop()
    logger.info("Agent 已退出")


def main() -> None:
    config = load_config()
    setup_logging(config.agent.log_level)
    try:
        asyncio.run(_run(config))
    except KeyboardInterrupt:
        logger.info("收到中断信号")


if __name__ == "__main__":
    main()
