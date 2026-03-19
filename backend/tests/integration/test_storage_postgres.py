"""
PostgreSQL 存储集成测试（testcontainers，需要 Docker）
PostgreSQL storage integration tests (testcontainers, requires Docker).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from orchestration.shared.enums import Role, TaskStatus
from orchestration.shared.types import CanonicalMessage, TextPart
from orchestration.storage.postgres.engine import (
    create_engine,
    create_session_factory,
    create_tables,
)
from orchestration.storage.postgres.repos.session_repo import SessionRepository
from orchestration.storage.postgres.repos.task_repo import TaskRepository
from orchestration.storage.postgres.repos.tenant_repo import TenantRepository
from tests.integration.conftest import integration, skip_if_no_docker

pytestmark = [integration, skip_if_no_docker]


# ---------------------------------------------------------------------------
# Engine fixture / 引擎 fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
async def pg_engine(postgres_container):
    """连接到 testcontainer PostgreSQL 实例。"""
    db_url = postgres_container.get_connection_url().replace(
        "postgresql://", "postgresql+asyncpg://"
    )
    engine = create_engine(db_url, pool_size=2, max_overflow=2)
    await create_tables(engine)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def db_session(pg_engine):
    """每个测试一个新 AsyncSession（自动回滚）。"""
    factory = create_session_factory(pg_engine)
    async with factory() as session:
        async with session.begin():
            yield session
            await session.rollback()


# ---------------------------------------------------------------------------
# Tenant tests / 租户测试
# ---------------------------------------------------------------------------

class TestTenantRepo:
    @pytest.mark.asyncio
    async def test_create_and_get(self, db_session: AsyncSession) -> None:
        repo = TenantRepository(db_session)
        tenant = await repo.create("test-tenant", settings={"tier": "free"})
        assert tenant.tenant_id is not None
        assert tenant.name == "test-tenant"

        fetched = await repo.get(tenant.tenant_id)
        assert fetched is not None
        assert fetched.name == "test-tenant"
        assert fetched.settings == {"tier": "free"}

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, db_session: AsyncSession) -> None:
        repo = TenantRepository(db_session)
        result = await repo.get(uuid.uuid4())
        assert result is None


# ---------------------------------------------------------------------------
# Session tests / 会话测试
# ---------------------------------------------------------------------------

class TestSessionRepo:
    @pytest.fixture()
    async def tenant_id(self, db_session: AsyncSession) -> str:
        repo = TenantRepository(db_session)
        tenant = await repo.create("session-test-tenant")
        return str(tenant.tenant_id)

    @pytest.mark.asyncio
    async def test_create_and_get_messages(
        self, db_session: AsyncSession, tenant_id: str
    ) -> None:
        repo = SessionRepository(db_session)
        msgs = [CanonicalMessage(role=Role.USER, content=[TextPart(text="hello")])]
        row = await repo.create(tenant_id, messages=msgs)

        fetched = await repo.get_messages(row.session_id, tenant_id)
        assert len(fetched) == 1
        assert isinstance(fetched[0].content[0], TextPart)
        assert fetched[0].content[0].text == "hello"

    @pytest.mark.asyncio
    async def test_append_messages(
        self, db_session: AsyncSession, tenant_id: str
    ) -> None:
        repo = SessionRepository(db_session)
        row = await repo.create(tenant_id)
        msg1 = CanonicalMessage(role=Role.USER, content=[TextPart(text="msg1")])
        msg2 = CanonicalMessage(role=Role.ASSISTANT, content=[TextPart(text="msg2")])

        await repo.append_messages(row.session_id, tenant_id, [msg1])
        await repo.append_messages(row.session_id, tenant_id, [msg2])
        msgs = await repo.get_messages(row.session_id, tenant_id)
        assert len(msgs) == 2

    @pytest.mark.asyncio
    async def test_char_count_updated(
        self, db_session: AsyncSession, tenant_id: str
    ) -> None:
        repo = SessionRepository(db_session)
        text = "x" * 100
        msgs = [CanonicalMessage(role=Role.USER, content=[TextPart(text=text)])]
        row = await repo.create(tenant_id, messages=msgs)
        assert row.char_count == 100


# ---------------------------------------------------------------------------
# Task tests / 任务测试
# ---------------------------------------------------------------------------

class TestTaskRepo:
    @pytest.fixture()
    async def tenant_id(self, db_session: AsyncSession) -> str:
        repo = TenantRepository(db_session)
        tenant = await repo.create("task-test-tenant")
        return str(tenant.tenant_id)

    @pytest.mark.asyncio
    async def test_create_and_get(
        self, db_session: AsyncSession, tenant_id: str
    ) -> None:
        repo = TaskRepository(db_session)
        row = await repo.create(tenant_id, input_data={"prompt": "test"})
        assert row.status == TaskStatus.PENDING.value

        fetched = await repo.get(row.task_id, tenant_id)
        assert fetched is not None
        assert fetched.input_data == {"prompt": "test"}

    @pytest.mark.asyncio
    async def test_update_status(
        self, db_session: AsyncSession, tenant_id: str
    ) -> None:
        repo = TaskRepository(db_session)
        row = await repo.create(tenant_id, input_data={})
        updated = await repo.update_status(
            row.task_id, tenant_id, TaskStatus.COMPLETED,
            result={"output": "done"},
        )
        assert updated.status == TaskStatus.COMPLETED.value
        assert updated.result == {"output": "done"}
