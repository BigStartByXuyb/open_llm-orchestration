"""
Bootstrap — 应用启动序列
Bootstrap — Application startup sequence.

Layer 5: May import from all layers.
第 5 层：可以从所有层导入。

职责 / Responsibilities:
  - 创建并启动 AppContainer
    Create and start AppContainer
  - 可选：在开发/测试模式下执行 DB 建表 + RLS 策略
    Optionally run DB table creation + RLS policies in dev/test mode
"""

from __future__ import annotations

import asyncio
import logging
import os

from orchestration.shared.config import Settings, get_settings
from orchestration.wiring.container import AppContainer
from orchestration.wiring.telemetry import configure_tracing

logger = logging.getLogger(__name__)

# Module-level singleton — set by create_container() / 模块级单例，由 create_container() 设置
_container: AppContainer | None = None


def get_container() -> AppContainer:
    """
    获取全局 AppContainer 单例
    Get the global AppContainer singleton.

    Raises RuntimeError if not yet initialized.
    未初始化时抛 RuntimeError。
    """
    if _container is None:
        raise RuntimeError(
            "AppContainer not initialized. "
            "Call await bootstrap() before handling requests."
        )
    return _container


async def bootstrap(settings: Settings | None = None) -> AppContainer:
    """
    创建并启动 AppContainer，存储为模块级单例
    Create and start AppContainer, store as module-level singleton.

    Called once during FastAPI lifespan startup.
    在 FastAPI lifespan startup 期间调用一次。

    Returns the initialized container.
    返回已初始化的容器。
    """
    global _container  # noqa: PLW0603

    s = settings or get_settings()

    # Initialize OTel TracerProvider before any request handling
    # 在请求处理前初始化 OTel TracerProvider
    configure_tracing(s)

    container = AppContainer(s)
    await container.startup()

    # Optional: auto-create tables in non-production environments
    # 可选：在非生产环境中自动建表
    if os.getenv("ORCH_AUTO_MIGRATE", "").lower() in ("1", "true", "yes"):
        from orchestration.storage.postgres.engine import create_tables, apply_rls_policies
        engine = container._infra.db_engine  # noqa: SLF001 (intentional access)
        if engine is not None:
            # Retry loop: Docker DNS may not resolve 'postgres' immediately after network creation
            # 重试循环：Docker DNS 在网络创建后可能无法立即解析 'postgres'
            for attempt in range(1, 6):
                try:
                    await create_tables(engine)
                    break
                except Exception as exc:
                    if attempt < 5:
                        logger.warning(
                            "create_tables attempt %d/5 failed: %s — retrying in 3s",
                            attempt, exc,
                        )
                        await asyncio.sleep(3)
                    else:
                        logger.error("create_tables failed after 5 attempts: %s", exc)
                        raise
            try:
                await apply_rls_policies(engine)
            except Exception as exc:
                # RLS may already be applied or require superuser; warn and continue
                # RLS 可能已应用或需要超级用户；警告并继续
                logger.warning("apply_rls_policies skipped: %s", exc)
        logger.info("Database tables ensured (ORCH_AUTO_MIGRATE=true)")

    _container = container
    logger.info("Bootstrap complete")
    return container


async def teardown() -> None:
    """
    关闭全局 AppContainer 并清理单例
    Shut down the global AppContainer and clean up the singleton.

    Called once during FastAPI lifespan shutdown.
    在 FastAPI lifespan shutdown 期间调用一次。
    """
    global _container  # noqa: PLW0603

    if _container is not None:
        await _container.shutdown()
        _container = None
        logger.info("AppContainer torn down")
