"""
异步 SQLAlchemy 引擎工厂
Async SQLAlchemy engine factory.

Layer 4: Only imports from shared/ and storage/postgres/models.py.

Usage / 使用方式:
  engine = create_engine(settings.DATABASE_URL)
  async_session_factory = create_session_factory(engine)
  async with async_session_factory() as session:
      ...
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from orchestration.shared.config import Settings
from orchestration.storage.postgres.models import Base, RLS_SETUP_SQL


def create_engine(database_url: str, *, pool_size: int = 10, max_overflow: int = 20) -> AsyncEngine:
    """
    创建 SQLAlchemy 异步引擎
    Create a SQLAlchemy async engine.
    """
    return create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,  # 连接健康检查 / Connection health check
        echo=False,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """
    创建异步 Session 工厂
    Create an async Session factory.
    """
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def create_engine_from_settings(s: Settings) -> AsyncEngine:
    """
    从 Settings 对象创建引擎（便捷函数）
    Create engine from Settings object (convenience function).
    """
    return create_engine(
        s.DATABASE_URL,
        pool_size=s.DATABASE_POOL_SIZE,
        max_overflow=s.DATABASE_MAX_OVERFLOW,
    )


async def create_tables(engine: AsyncEngine) -> None:
    """
    创建所有表（开发/测试用；生产使用 Alembic 迁移）
    Create all tables (dev/test use; production uses Alembic migrations).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def apply_rls_policies(engine: AsyncEngine) -> None:
    """
    应用 RLS 策略（首次建表后执行）
    Apply RLS policies (run once after table creation).

    Must be called with a superuser / 必须以超级用户执行。
    """
    from sqlalchemy import text

    async with engine.begin() as conn:
        for stmt in RLS_SETUP_SQL:
            await conn.execute(text(stmt))
