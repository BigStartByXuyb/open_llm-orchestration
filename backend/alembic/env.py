"""
Alembic migration environment.

与 models.py 中的 Base.metadata 绑定，支持在线和离线迁移模式。
Bound to Base.metadata from models.py; supports both online and offline migration modes.

DATABASE_URL 解析 / DATABASE_URL resolution:
  1. 从环境变量 ORCH_DATABASE_URL 读取（pydantic Settings）
  2. 将 asyncpg 驱动替换为 psycopg2（Alembic 需要同步驱动）
  3. 若未配置，回退到 alembic.ini 中的 sqlalchemy.url

使用方式 / Usage:
  cd backend
  alembic upgrade head          # 应用所有迁移
  alembic downgrade -1          # 回滚最近一次迁移
  alembic revision --autogenerate -m "add new table"  # 自动生成迁移
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Add src/ to sys.path so we can import orchestration.*
# ---------------------------------------------------------------------------

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_SRC_DIR = _BACKEND_DIR / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

# ---------------------------------------------------------------------------
# Import application metadata and settings
# ---------------------------------------------------------------------------

from orchestration.storage.postgres.models import Base  # noqa: E402
from orchestration.shared.config import get_settings     # noqa: E402

target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Resolve sync database URL from ORCH_DATABASE_URL env var
# ---------------------------------------------------------------------------


def _get_sync_url() -> str:
    """
    获取同步 SQLAlchemy URL（替换 asyncpg → psycopg2）。
    Get sync SQLAlchemy URL (replace asyncpg driver with psycopg2).
    """
    try:
        settings = get_settings()
        url = settings.DATABASE_URL
    except Exception:
        # Fallback to alembic.ini value if Settings can't be initialised
        url = config.get_main_option("sqlalchemy.url", "")

    # Convert async driver to sync for Alembic
    url = url.replace("+asyncpg", "+psycopg2").replace("+aiosqlite", "")
    return url


# ---------------------------------------------------------------------------
# Offline migration mode (generates SQL without connecting)
# 离线迁移模式（生成 SQL，不连接数据库）
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """
    在离线模式下运行迁移，输出 SQL 而不连接数据库。
    Run migrations in 'offline' mode, emitting SQL without connecting.
    """
    url = _get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migration mode (connects to database and applies migrations)
# 在线迁移模式（连接数据库并应用迁移）
# ---------------------------------------------------------------------------


def run_migrations_online() -> None:
    """
    在在线模式下运行迁移，直接连接数据库。
    Run migrations in 'online' mode by connecting to the database directly.
    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_sync_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
