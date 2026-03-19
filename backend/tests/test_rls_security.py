"""
RLS 安全隔离集成测试（testcontainers — 需要 Docker）
RLS security isolation integration tests (testcontainers — requires Docker).

验证 PostgreSQL Row Level Security 多租户隔离：
Verifies PostgreSQL Row Level Security multi-tenant isolation:
  1. Tenant A 的数据对 Tenant B 不可见
     Tenant A's data is invisible to Tenant B
  2. 不注入 tenant_id 时 deny_by_default 策略生效（返回空集）
     deny_by_default policy fires when no tenant_id is injected (returns empty set)
  3. 列表查询仅返回本租户数据
     List queries return only own-tenant data

所有测试标记为 integration（需要 Docker）/ All tests marked integration (requires Docker).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from orchestration.storage.postgres.engine import (
    create_engine,
    create_session_factory,
    create_tables,
    apply_rls_policies,
)
from orchestration.storage.postgres.repos.session_repo import SessionRepository
from orchestration.storage.postgres.repos.task_repo import TaskRepository
from orchestration.storage.postgres.repos.tenant_repo import TenantRepository
from tests.integration.conftest import integration, skip_if_no_docker

pytestmark = [integration, skip_if_no_docker]


# ---------------------------------------------------------------------------
# Engine + session fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def rls_engine(postgres_container):
    """
    带 RLS 策略的 PostgreSQL 引擎（模块作用域）
    PostgreSQL engine with RLS policies applied (module scope).

    与 test_storage_postgres.py 中的 pg_engine 分开，确保 RLS 策略生效。
    Separate from pg_engine in test_storage_postgres.py to ensure RLS is active.
    """
    db_url = postgres_container.get_connection_url().replace(
        "postgresql://", "postgresql+asyncpg://"
    )
    engine = create_engine(db_url, pool_size=2, max_overflow=2)
    await create_tables(engine)
    await apply_rls_policies(engine)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def rls_session(rls_engine):
    """每测试一个事务（自动回滚）/ One transaction per test (auto-rollback)."""
    factory = create_session_factory(rls_engine)
    async with factory() as session:
        async with session.begin():
            yield session
            await session.rollback()


# ---------------------------------------------------------------------------
# Helpers / 辅助函数
# ---------------------------------------------------------------------------


async def _create_tenant(session: AsyncSession, name: str) -> str:
    """创建租户，返回 tenant_id 字符串 / Create tenant, return tenant_id string."""
    repo = TenantRepository(session)
    tenant = await repo.create(name)
    return str(tenant.tenant_id)


# ---------------------------------------------------------------------------
# Tests: session isolation / 会话隔离测试
# ---------------------------------------------------------------------------


class TestSessionRLSIsolation:
    """验证 sessions 表的 RLS 多租户隔离 / Verify RLS isolation on sessions table."""

    @pytest.mark.asyncio
    async def test_tenant_b_cannot_see_tenant_a_session(self, rls_engine) -> None:
        """
        Tenant B 无法读取 Tenant A 的 session（RLS tenant_isolation 策略）
        Tenant B cannot read Tenant A's session (RLS tenant_isolation policy).
        """
        factory = create_session_factory(rls_engine)

        # Step 1: Create tenants (tenants table has NO RLS)
        # 步骤 1：创建租户（tenants 表没有 RLS）
        async with factory() as session:
            async with session.begin():
                tenant_a = await _create_tenant(session, f"rls-a-{uuid.uuid4().hex[:8]}")
                tenant_b = await _create_tenant(session, f"rls-b-{uuid.uuid4().hex[:8]}")

        # Step 2: Create a session for Tenant A
        # 步骤 2：为 Tenant A 创建 session（committed）
        session_id: uuid.UUID
        async with factory() as session:
            async with session.begin():
                repo = SessionRepository(session)
                row = await repo.create(tenant_a)
                session_id = row.session_id

        # Step 3: Tenant B tries to read it → must get None
        # 步骤 3：Tenant B 尝试读取 → 必须得到 None
        async with factory() as session:
            async with session.begin():
                repo = SessionRepository(session)
                result = await repo.get(session_id, tenant_b)
                assert result is None, (
                    "RLS violation: Tenant B must not see Tenant A's session"
                )

        # Step 4: Tenant A reads its own session → must succeed
        # 步骤 4：Tenant A 读取自己的 session → 必须成功
        async with factory() as session:
            async with session.begin():
                repo = SessionRepository(session)
                result = await repo.get(session_id, tenant_a)
                assert result is not None, (
                    "RLS error: Tenant A must see its own session"
                )
                assert result.session_id == session_id

    @pytest.mark.asyncio
    async def test_deny_by_default_without_tenant_injection(self, rls_engine) -> None:
        """
        不注入 tenant_id 时，deny_by_default 策略使 sessions 全表不可见
        Without tenant_id injection, deny_by_default makes all sessions invisible.
        """
        factory = create_session_factory(rls_engine)

        # Direct SQL without SET LOCAL → deny_by_default (USING false) → 0 rows
        # 不设置 SET LOCAL → deny_by_default（USING false）→ 0 行
        async with factory() as session:
            async with session.begin():
                result = await session.execute(text("SELECT COUNT(*) FROM sessions"))
                count = result.scalar()
                assert count == 0, (
                    f"deny_by_default must return 0 rows without tenant injection; "
                    f"got {count}"
                )

    @pytest.mark.asyncio
    async def test_list_sessions_returns_only_own_tenant_data(
        self, rls_engine
    ) -> None:
        """
        list_sessions 只返回本租户数据，跨租户数据不可见
        list_sessions returns only own-tenant data; cross-tenant data is invisible.
        """
        factory = create_session_factory(rls_engine)

        # Create two tenants with unique names
        async with factory() as session:
            async with session.begin():
                uid = uuid.uuid4().hex[:8]
                ta = await _create_tenant(session, f"list-ta-{uid}")
                tb = await _create_tenant(session, f"list-tb-{uid}")

        # Create 2 sessions for Tenant A, 1 session for Tenant B
        async with factory() as session:
            async with session.begin():
                repo = SessionRepository(session)
                await repo.create(ta)
                await repo.create(ta)

        async with factory() as session:
            async with session.begin():
                repo = SessionRepository(session)
                await repo.create(tb)

        # Tenant A → should see exactly 2 sessions
        async with factory() as session:
            async with session.begin():
                repo = SessionRepository(session)
                sessions = await repo.list_sessions(ta)
                assert len(sessions) == 2, (
                    f"Tenant A should see 2 sessions; got {len(sessions)}"
                )

        # Tenant B → should see exactly 1 session
        async with factory() as session:
            async with session.begin():
                repo = SessionRepository(session)
                sessions = await repo.list_sessions(tb)
                assert len(sessions) == 1, (
                    f"Tenant B should see 1 session; got {len(sessions)}"
                )


# ---------------------------------------------------------------------------
# Tests: task isolation / 任务隔离测试
# ---------------------------------------------------------------------------


class TestTaskRLSIsolation:
    """验证 tasks 表的 RLS 多租户隔离 / Verify RLS isolation on tasks table."""

    @pytest.mark.asyncio
    async def test_tenant_b_cannot_see_tenant_a_task(self, rls_engine) -> None:
        """
        Tenant B 无法读取 Tenant A 的 task（RLS tenant_isolation 策略）
        Tenant B cannot read Tenant A's task (RLS tenant_isolation policy).
        """
        factory = create_session_factory(rls_engine)

        async with factory() as session:
            async with session.begin():
                uid = uuid.uuid4().hex[:8]
                ta = await _create_tenant(session, f"task-ta-{uid}")
                tb = await _create_tenant(session, f"task-tb-{uid}")

        # Create a task for Tenant A
        task_id: uuid.UUID
        async with factory() as session:
            async with session.begin():
                repo = TaskRepository(session)
                row = await repo.create(ta, input_data={"prompt": "test"})
                task_id = row.task_id

        # Tenant B tries to read → must get None
        async with factory() as session:
            async with session.begin():
                repo = TaskRepository(session)
                result = await repo.get(task_id, tb)
                assert result is None, (
                    "RLS violation: Tenant B must not see Tenant A's task"
                )

        # Tenant A reads its own task → must succeed
        async with factory() as session:
            async with session.begin():
                repo = TaskRepository(session)
                result = await repo.get(task_id, ta)
                assert result is not None, "RLS error: Tenant A must see its own task"
                assert result.task_id == task_id

    @pytest.mark.asyncio
    async def test_deny_by_default_without_tenant_injection_tasks(
        self, rls_engine
    ) -> None:
        """
        不注入 tenant_id 时，deny_by_default 策略使 tasks 全表不可见
        Without tenant_id injection, deny_by_default makes all tasks invisible.
        """
        factory = create_session_factory(rls_engine)

        async with factory() as session:
            async with session.begin():
                result = await session.execute(text("SELECT COUNT(*) FROM tasks"))
                count = result.scalar()
                assert count == 0, (
                    f"deny_by_default must return 0 task rows without tenant injection; "
                    f"got {count}"
                )
