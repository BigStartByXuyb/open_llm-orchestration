"""
FastAPI 依赖注入器
FastAPI dependency injectors.

Layer 1: Accesses AppContainer (Layer 5) via module import.
第 1 层：通过模块导入访问 AppContainer（第 5 层）。

所有 FastAPI 路由通过这些依赖函数获取所需实例，无需直接接触 wiring 层。
All FastAPI routes obtain required instances through these dependency functions
without touching the wiring layer directly.
"""

from __future__ import annotations

from typing import Annotated, AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from orchestration.shared.types import RunContext
from orchestration.wiring.bootstrap import get_container
from orchestration.wiring.container import AppContainer
from orchestration.orchestration.engine import OrchestrationEngine
from orchestration.storage.postgres.repos.session_repo import SessionRepository
from orchestration.storage.postgres.repos.task_repo import TaskRepository
from orchestration.storage.postgres.repos.tenant_repo import TenantRepository
from orchestration.storage.redis.task_state import TaskStateStore
from orchestration.storage.redis.rate_limit_store import RateLimitStore
from orchestration.storage.billing.billing_repo import BillingRepository
from orchestration.storage.vector.vector_store import EmbeddingRepository
from orchestration.storage.postgres.repos.tenant_key_repo import TenantKeyRepository


# ---------------------------------------------------------------------------
# Container / 容器
# ---------------------------------------------------------------------------


def get_app_container(request: Request) -> AppContainer:
    """
    从 request.app.state 获取 AppContainer 单例
    Get AppContainer singleton from request.app.state.
    """
    return request.app.state.container  # type: ignore[no-any-return]


ContainerDep = Annotated[AppContainer, Depends(get_app_container)]


# ---------------------------------------------------------------------------
# Engine / 引擎
# ---------------------------------------------------------------------------


def get_engine(container: ContainerDep) -> OrchestrationEngine:
    """获取 OrchestrationEngine / Get OrchestrationEngine."""
    return container.engine


EngineDep = Annotated[OrchestrationEngine, Depends(get_engine)]


# ---------------------------------------------------------------------------
# DB Session / 数据库 Session
# ---------------------------------------------------------------------------


async def get_db_session(container: ContainerDep) -> AsyncIterator[AsyncSession]:
    """
    每次请求创建一个新的 AsyncSession，成功时提交，异常时回滚
    Create a new AsyncSession per request, commit on success, rollback on exception.
    """
    async with container.db_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


DBSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


# ---------------------------------------------------------------------------
# Repositories / 仓库
# ---------------------------------------------------------------------------


def get_session_repo(
    db: DBSessionDep,
    container: ContainerDep,
) -> SessionRepository:
    return container.make_session_repo(db)


def get_task_repo(
    db: DBSessionDep,
    container: ContainerDep,
) -> TaskRepository:
    return container.make_task_repo(db)


def get_tenant_repo(
    db: DBSessionDep,
    container: ContainerDep,
) -> TenantRepository:
    return container.make_tenant_repo(db)


SessionRepoDep = Annotated[SessionRepository, Depends(get_session_repo)]
TaskRepoDep = Annotated[TaskRepository, Depends(get_task_repo)]
TenantRepoDep = Annotated[TenantRepository, Depends(get_tenant_repo)]


# ---------------------------------------------------------------------------
# Redis stores / Redis 存储
# ---------------------------------------------------------------------------


def get_task_state_store(container: ContainerDep) -> TaskStateStore:
    return container.make_task_state_store()


def get_rate_limit_store(container: ContainerDep) -> RateLimitStore:
    return container.make_rate_limit_store()


TaskStateStoreDep = Annotated[TaskStateStore, Depends(get_task_state_store)]
RateLimitStoreDep = Annotated[RateLimitStore, Depends(get_rate_limit_store)]


# ---------------------------------------------------------------------------
# Billing repository / 计费仓库
# ---------------------------------------------------------------------------


def get_billing_repo(
    db: DBSessionDep,
    container: ContainerDep,
) -> BillingRepository:
    return container.make_billing_repo(db)


BillingRepoDep = Annotated[BillingRepository, Depends(get_billing_repo)]


# ---------------------------------------------------------------------------
# Embedding repository / 向量嵌入仓库
# ---------------------------------------------------------------------------


def get_embedding_repo(
    db: DBSessionDep,
    container: ContainerDep,
) -> EmbeddingRepository:
    return container.make_embedding_repo(db)


EmbeddingRepoDep = Annotated[EmbeddingRepository, Depends(get_embedding_repo)]


# ---------------------------------------------------------------------------
# Tenant key repository / 租户 API Key 仓库
# ---------------------------------------------------------------------------


def get_tenant_key_repo(
    db: DBSessionDep,
    container: ContainerDep,
) -> TenantKeyRepository:
    return container.make_tenant_key_repo(db)


TenantKeyRepoDep = Annotated[TenantKeyRepository, Depends(get_tenant_key_repo)]


# ---------------------------------------------------------------------------
# Run context / 运行上下文
# ---------------------------------------------------------------------------


def get_run_context(request: Request) -> RunContext:
    """
    从请求状态获取已注入的 RunContext
    Get the RunContext that was injected by tenant middleware.

    Raises RuntimeError if middleware did not inject context (should not happen).
    如果中间件未注入上下文（不应发生），则抛 RuntimeError。
    """
    context: RunContext | None = getattr(request.state, "run_context", None)
    if context is None:
        raise RuntimeError(
            "RunContext not found in request.state. "
            "Ensure TenantMiddleware is installed and runs before this endpoint."
        )
    return context


RunContextDep = Annotated[RunContext, Depends(get_run_context)]
