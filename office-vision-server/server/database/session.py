"""数据库会话管理。

生产：PostgreSQL（asyncpg）；开发与测试：SQLite（aiosqlite）。
URL 来自 config/server.yaml，禁止硬编码。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from server.database import models  # noqa: F401  注册模型元数据
from server.database.base import Base

__all__ = ["Base", "Database"]

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SQLITE_PREFIX = "sqlite+aiosqlite:///"


def _prepare_sqlite_path(url: str) -> str:
    """SQLite 相对路径统一到项目根并确保目录存在。"""
    if not url.startswith(_SQLITE_PREFIX) or url.startswith(_SQLITE_PREFIX + "/"):
        return url
    rel = url.removeprefix(_SQLITE_PREFIX)
    path = _PROJECT_ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"{_SQLITE_PREFIX}{path}"


def _sqlite_connect_pragma(dbapi_conn, _connection_record) -> None:
    """SQLite 连接初始化：WAL 模式 + busy_timeout，避免写锁导致读查询 500。

    - WAL：读写并发，读不被写事务阻塞（修复间歇性 database is locked）。
    - busy_timeout=5000：拿不到锁时等待 5s 而非直接报错。
    - synchronous=NORMAL：WAL 下降低 fsync 压力（写多，性能友好）。
    """
    cursor = dbapi_conn.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


class Database:
    """引擎 + 会话工厂的生命周期封装。"""

    def __init__(self, url: str, echo: bool = False) -> None:
        self._engine: AsyncEngine = create_async_engine(_prepare_sqlite_path(url), echo=echo)
        if url.startswith(_SQLITE_PREFIX):
            event.listen(self._engine.sync_engine, "connect", _sqlite_connect_pragma)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    async def create_all(self) -> None:
        """开发/测试环境直接建表；生产使用 Alembic 迁移。"""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def session_scope(self) -> AsyncIterator[AsyncSession]:
        """会话上下文（自动关闭）。"""
        async with self._session_factory() as session:
            yield session

    async def session(self) -> AsyncIterator[AsyncSession]:
        """FastAPI 依赖注入用。"""
        async with self._session_factory() as session:
            yield session

    async def close(self) -> None:
        await self._engine.dispose()
