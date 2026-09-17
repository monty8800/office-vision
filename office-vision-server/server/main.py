"""Server 入口：FastAPI 应用工厂。

职责：
- 接收 Agent 事件（POST /api/events）并持久化
- Dashboard 查询 API（统计 / 记录 / 趋势 / 在岗状态 / Agent 在线）
- 不接触摄像头、不做视觉推理（第一原则）

运行：uv run uvicorn server.main:app（配置来自 config/server.yaml）
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from loguru import logger
from sqlalchemy import delete

from server.api.routes import events as event_routes
from server.api.routes import logs as logs_routes
from server.api.routes import sitting as sitting_routes
from server.api.routes import stats as stats_routes
from server.core.config import ServerConfig, load_config
from server.core.logging import setup_logging
from server.database.migrate import migrate_smoking_to_behavior
from server.database.models import ClientLog
from server.database.session import Database

_MAINTENANCE_INTERVAL_SECONDS = 6 * 3600  # 日志保留维护：每 6 小时一次


def _vacuum_sqlite(path: str) -> None:
    """用 stdlib sqlite3 单独连接执行 VACUUM（需 autocommit，且不能在事务内）。"""
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA busy_timeout=60000")
        conn.execute("VACUUM")
    finally:
        conn.close()


async def _maintenance_loop(db: Database, settings: ServerConfig) -> None:
    """定期清理超过保留期的客户端日志并 VACUUM 收缩。

    DELETE 只释放页、不缩小文件；只有 VACUUM 才能真正把库瘦回去，
    否则文件长期停留在历史最高水位（曾把库撑到 1.5G+）。
    """
    retention_days = int(getattr(settings.logs, "retention_days", 14) or 14)
    while True:
        await asyncio.sleep(_MAINTENANCE_INTERVAL_SECONDS)
        try:
            cutoff = datetime.now(UTC) - timedelta(days=retention_days)
            async with db.session_scope() as session:
                result = await session.execute(
                    delete(ClientLog).where(ClientLog.received_at < cutoff)
                )
                await session.commit()
                deleted = result.rowcount or 0
            if deleted:
                path = db.engine.url.database
                if path:
                    await asyncio.to_thread(_vacuum_sqlite, path)
                logger.info("日志保留维护：删除 {} 条超过 {} 天的日志并 VACUUM", deleted, retention_days)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("日志保留维护异常（下一轮重试）")


def create_app(database_url: str, config: ServerConfig | None = None) -> FastAPI:
    """应用工厂；database_url 显式传入（生产读配置，测试用 SQLite）。"""
    settings = config or load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(database_url)
        await db.create_all()
        async with db.session_scope() as session:  # 旧抽烟表一次性迁移（幂等）
            await migrate_smoking_to_behavior(session)
        app.state.db = db
        app.state.config = settings
        maintenance = asyncio.create_task(_maintenance_loop(db, settings))
        logger.info("Server 已启动（数据库就绪）")
        try:
            yield
        finally:
            maintenance.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await maintenance
            await db.close()
            logger.info("Server 已停止")

    app = FastAPI(
        title="Office Vision Server",
        description="事件处理、存储与 Dashboard API",
        lifespan=lifespan,
    )
    app.include_router(event_routes.router)
    app.include_router(logs_routes.router)
    app.include_router(stats_routes.router)
    app.include_router(sitting_routes.router)

    @app.get("/api/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


# uvicorn server.main:app 入口；引擎懒连接，导入时不会真正连库
_config = load_config()
setup_logging(_config.server.log_level)
app = create_app(_config.database_url)
