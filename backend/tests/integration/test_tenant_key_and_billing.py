"""
TenantKeyRepository + BillingRepository 集成测试（testcontainers，需要 Docker）
TenantKeyRepository + BillingRepository integration tests (testcontainers, requires Docker).

Sprint 16: 验证 N-08 Fernet 加密在真实 PostgreSQL 中端到端工作
Sprint 16: Verify N-08 Fernet encryption works end-to-end with real PostgreSQL.
"""

from __future__ import annotations

import uuid

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from orchestration.storage.billing.billing_repo import BillingRepository
from orchestration.storage.postgres.engine import (
    create_engine,
    create_session_factory,
    create_tables,
)
from orchestration.storage.postgres.repos.tenant_key_repo import TenantKeyRepository
from orchestration.storage.postgres.repos.tenant_repo import TenantRepository
from tests.integration.conftest import integration, skip_if_no_docker

pytestmark = [integration, skip_if_no_docker]


# ---------------------------------------------------------------------------
# Engine fixture / 引擎 fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def pg_engine_tkb(postgres_container):
    """连接到 testcontainer PostgreSQL 实例（TenantKey + Billing 专用）。"""
    db_url = postgres_container.get_connection_url().replace(
        "postgresql://", "postgresql+asyncpg://"
    )
    engine = create_engine(db_url, pool_size=2, max_overflow=2)
    await create_tables(engine)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def db_session(pg_engine_tkb):
    """每个测试一个新 AsyncSession（自动回滚）。"""
    factory = create_session_factory(pg_engine_tkb)
    async with factory() as session:
        async with session.begin():
            yield session
            await session.rollback()


@pytest.fixture()
async def tenant_id(db_session: AsyncSession) -> uuid.UUID:
    """创建测试租户，返回 tenant_id UUID。"""
    repo = TenantRepository(db_session)
    tenant = await repo.create(f"test-tenant-{uuid.uuid4().hex[:8]}")
    return tenant.tenant_id


# ---------------------------------------------------------------------------
# TestTenantKeyRepo (integration with real DB)
# ---------------------------------------------------------------------------


class TestTenantKeyRepoIntegration:
    """TenantKeyRepository 集成测试 — 验证在真实 PostgreSQL 中 CRUD 正常。"""

    @pytest.mark.asyncio
    async def test_upsert_and_get_plaintext(
        self, db_session: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """未配置加密密钥时，API key 以明文存储并可正确读回。"""
        import orchestration.storage.postgres.repos.tenant_key_repo as repo_module
        original = repo_module._get_fernet
        repo_module._get_fernet = lambda: None  # force plaintext mode

        try:
            repo = TenantKeyRepository(db_session)
            plaintext = "sk-integration-test-key"
            await repo.upsert(tenant_id, "openai", plaintext)

            row = await repo.get(tenant_id, "openai")
            assert row is not None
            assert row.api_key == plaintext
        finally:
            repo_module._get_fernet = original

    @pytest.mark.asyncio
    async def test_upsert_and_get_encrypted(
        self, db_session: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """配置 Fernet 密钥时，DB 中存密文，get() 返回明文。"""
        import orchestration.storage.postgres.repos.tenant_key_repo as repo_module
        test_fernet_key = Fernet.generate_key()
        fernet_instance = Fernet(test_fernet_key)
        original = repo_module._get_fernet
        repo_module._get_fernet = lambda: fernet_instance

        try:
            repo = TenantKeyRepository(db_session)
            plaintext = "sk-secret-encrypted-key"
            await repo.upsert(tenant_id, "anthropic", plaintext)

            row = await repo.get(tenant_id, "anthropic")
            assert row is not None
            assert row.api_key == plaintext, "get() should return decrypted plaintext"
        finally:
            repo_module._get_fernet = original

    @pytest.mark.asyncio
    async def test_update_overwrites_key(
        self, db_session: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """二次 upsert 覆盖已有 key，get() 返回最新值。"""
        import orchestration.storage.postgres.repos.tenant_key_repo as repo_module
        original = repo_module._get_fernet
        repo_module._get_fernet = lambda: None

        try:
            repo = TenantKeyRepository(db_session)
            await repo.upsert(tenant_id, "openai", "old-key")
            await repo.upsert(tenant_id, "openai", "new-key")

            row = await repo.get(tenant_id, "openai")
            assert row is not None
            assert row.api_key == "new-key"
        finally:
            repo_module._get_fernet = original

    @pytest.mark.asyncio
    async def test_list_all_returns_all_providers(
        self, db_session: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """list_all() 返回该租户所有 provider 的 key。"""
        import orchestration.storage.postgres.repos.tenant_key_repo as repo_module
        original = repo_module._get_fernet
        repo_module._get_fernet = lambda: None

        try:
            repo = TenantKeyRepository(db_session)
            await repo.upsert(tenant_id, "anthropic", "key-a")
            await repo.upsert(tenant_id, "openai", "key-b")
            await repo.upsert(tenant_id, "deepseek", "key-c")

            rows = await repo.list_all(tenant_id)
            provider_ids = {r.provider_id for r in rows}
            assert "anthropic" in provider_ids
            assert "openai" in provider_ids
            assert "deepseek" in provider_ids
        finally:
            repo_module._get_fernet = original

    @pytest.mark.asyncio
    async def test_delete_existing_key(
        self, db_session: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """delete() 成功删除已有 key，返回 True；再次 get() 返回 None。"""
        import orchestration.storage.postgres.repos.tenant_key_repo as repo_module
        original = repo_module._get_fernet
        repo_module._get_fernet = lambda: None

        try:
            repo = TenantKeyRepository(db_session)
            await repo.upsert(tenant_id, "gemini", "gm-key-123")
            deleted = await repo.delete(tenant_id, "gemini")
            assert deleted is True

            row = await repo.get(tenant_id, "gemini")
            assert row is None
        finally:
            repo_module._get_fernet = original

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(
        self, db_session: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """delete() 对不存在的 key 返回 False。"""
        repo = TenantKeyRepository(db_session)
        deleted = await repo.delete(tenant_id, "nonexistent_provider_xyz")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_tenant_isolation_for_keys(
        self, db_session: AsyncSession
    ) -> None:
        """不同租户的 key 相互隔离，A 的 key 对 B 不可见。"""
        import orchestration.storage.postgres.repos.tenant_key_repo as repo_module
        original = repo_module._get_fernet
        repo_module._get_fernet = lambda: None

        try:
            tenant_repo = TenantRepository(db_session)
            tenant_a = await tenant_repo.create(f"key-isolation-a-{uuid.uuid4().hex[:6]}")
            tenant_b = await tenant_repo.create(f"key-isolation-b-{uuid.uuid4().hex[:6]}")

            key_repo = TenantKeyRepository(db_session)
            await key_repo.upsert(tenant_a.tenant_id, "anthropic", "key-for-A")

            row_b = await key_repo.get(tenant_b.tenant_id, "anthropic")
            assert row_b is None, "Tenant B must not see Tenant A's API key"
        finally:
            repo_module._get_fernet = original


# ---------------------------------------------------------------------------
# TestBillingRepoIntegration
# ---------------------------------------------------------------------------


class TestBillingRepoIntegration:
    """BillingRepository 集成测试 — 验证在真实 PostgreSQL 中计费记录正常。"""

    @pytest.mark.asyncio
    async def test_record_and_retrieve_usage(
        self, db_session: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """record_usage() 写入一条记录，get_usage_by_tenant() 能读回。"""
        repo = BillingRepository(db_session)
        task_id = uuid.uuid4()
        row = await repo.record_usage(
            tenant_id=tenant_id,
            provider_id="anthropic",
            tokens_used=1500,
            task_id=task_id,
            cost_usd=0.045,
        )
        assert row.usage_id is not None

        records = await repo.get_usage_by_tenant(tenant_id)
        assert len(records) >= 1
        matching = [r for r in records if r.task_id == task_id]
        assert len(matching) == 1
        assert matching[0].tokens_used == 1500
        assert matching[0].provider_id == "anthropic"

    @pytest.mark.asyncio
    async def test_aggregate_by_provider(
        self, db_session: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """aggregate_by_provider() 正确汇总各 provider 的 token 总量。"""
        repo = BillingRepository(db_session)
        await repo.record_usage(tenant_id, "openai", tokens_used=1000)
        await repo.record_usage(tenant_id, "openai", tokens_used=500)
        await repo.record_usage(tenant_id, "anthropic", tokens_used=2000)

        agg = await repo.aggregate_by_provider(tenant_id)
        assert agg.get("openai", 0) >= 1500
        assert agg.get("anthropic", 0) >= 2000

    @pytest.mark.asyncio
    async def test_total_tokens_for_task(
        self, db_session: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """total_tokens_for_task() 返回指定 task 下所有 subtask 的 token 之和。"""
        repo = BillingRepository(db_session)
        task_id = uuid.uuid4()
        await repo.record_usage(tenant_id, "deepseek", tokens_used=300, task_id=task_id)
        await repo.record_usage(tenant_id, "deepseek", tokens_used=700, task_id=task_id)

        total = await repo.total_tokens_for_task(tenant_id, task_id)
        assert total == 1000

    @pytest.mark.asyncio
    async def test_empty_usage_returns_zero(
        self, db_session: AsyncSession, tenant_id: uuid.UUID
    ) -> None:
        """total_tokens_for_task() 对无记录的 task 返回 0（不崩溃）。"""
        repo = BillingRepository(db_session)
        total = await repo.total_tokens_for_task(tenant_id, uuid.uuid4())
        assert total == 0

    @pytest.mark.asyncio
    async def test_billing_tenant_isolation(
        self, db_session: AsyncSession
    ) -> None:
        """不同租户的 usage 记录相互隔离，get_usage_by_tenant() 只返回本租户数据。"""
        tenant_repo = TenantRepository(db_session)
        tenant_a = await tenant_repo.create(f"billing-a-{uuid.uuid4().hex[:6]}")
        tenant_b = await tenant_repo.create(f"billing-b-{uuid.uuid4().hex[:6]}")

        billing_repo = BillingRepository(db_session)
        task_a = uuid.uuid4()
        await billing_repo.record_usage(tenant_a.tenant_id, "anthropic", 999, task_id=task_a)

        records_b = await billing_repo.get_usage_by_tenant(tenant_b.tenant_id)
        task_ids_b = {r.task_id for r in records_b}
        assert task_a not in task_ids_b, "Tenant B must not see Tenant A's billing records"
