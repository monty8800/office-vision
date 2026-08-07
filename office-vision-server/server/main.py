"""Server 入口：FastAPI 应用工厂。

职责：
- 接收 Agent 事件（POST /api/events）并持久化
- Dashboard 查询 API（统计 / 记录 / 趋势 / 在岗状态 / Agent 在线）
- 不接触摄像头、不做视觉推理（第一原则）

运行：uv run uvicorn server.main:app（配置来自 config/server.yaml）
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from server.api.routes import events as event_routes
from server.api.routes import stats as stats_routes
from server.core.config import ServerConfig, load_config
from server.core.logging import setup_logging
from server.database.session import Database


def create_app(database_url: str, config: ServerConfig | None = None) -> FastAPI:
    """应用工厂；database_url 显式传入（生产读配置，测试用 SQLite）。"""
    settings = config or load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(database_url)
        await db.create_all()
        app.state.db = db
        app.state.config = settings
        logger.info("Server 已启动（数据库就绪）")
        yield
        await db.close()
        logger.info("Server 已停止")

    app = FastAPI(
        title="Office Vision Server",
        description="事件处理、存储与 Dashboard API",
        lifespan=lifespan,
    )
    app.include_router(event_routes.router)
    app.include_router(stats_routes.router)

    @app.get("/api/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


# uvicorn server.main:app 入口；引擎懒连接，导入时不会真正连库
_config = load_config()
setup_logging(_config.server.log_level)
app = create_app(_config.database_url)
