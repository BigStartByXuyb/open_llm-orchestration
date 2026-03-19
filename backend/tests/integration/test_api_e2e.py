"""
API 端到端集成测试（testcontainers + 真实 PostgreSQL）
API end-to-end integration tests (testcontainers + real PostgreSQL).

Sprint 16: 验证 HTTP 路由 → 依赖注入 → 真实 DB 的完整链路
Sprint 16: Verify full chain: HTTP route → DI → real DB.

使用 FastAPI TestClient + 真实 PostgreSQL + 模拟 AppContainer（仅注入 db_session_factory）。
Uses FastAPI TestClient + real PostgreSQL + minimal mocked AppContainer (only db_session_factory).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from orchestration.gateway.middleware.auth import AuthMiddleware, create_access_token
from orchestration.gateway.middleware.tenant import TenantMiddleware
from orchestration.gateway.routers import tenant_keys, sessions
from orchestration.shared.config import Settings
from orchestration.shared.types import RunContext
from orchestration.storage.postgres.engine import (
    create_engine,
    create_session_factory,
    create_tables,
)
from orchestration.storage.postgres.repos.session_repo import SessionRepository
from orchestration.storage.postgres.repos.tenant_key_repo import TenantKeyRepository
from orchestration.storage.postgres.repos.tenant_repo import TenantRepository
from tests.integration.conftest import integration, skip_if_no_docker

pytestmark = [integration, skip_if_no_docker]


# ---------------------------------------------------------------------------
# Test settings / 测试配置
# ---------------------------------------------------------------------------

E2E_SETTINGS = Settings(
    JWT_SECRET_KEY="e2e-test-secret-key",
    DATABASE_URL="postgresql+asyncpg://unused/e2e",
    REDIS_URL="redis://localhost:6379/0",
)

TENANT_ID = "e2e-tenant-" + uuid.uuid4().hex[:8]
USER_ID = "e2e-user-1"


# ---------------------------------------------------------------------------
# Engine fixture (module scope)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
async def e2e_engine(postgres_container):
    """为 E2E 测试创建独立的数据库引擎和表结构。"""
    db_url = postgres_container.get_connection_url().replace(
        "postgresql://", "postgresql+asyncpg://"
    )
    engine = create_engine(db_url, pool_size=2, max_overflow=2)
    await create_tables(engine)
    yield engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# App builder — minimal container using real DB session factory
# ---------------------------------------------------------------------------


def _build_e2e_app(session_factory) -> FastAPI:
    """
    构建测试用 FastAPI 应用，容器只注入真实 db_session_factory。
    Build test FastAPI app; container provides only real db_session_factory.
    """
    app = FastAPI()

    # Build a minimal mock container that injects a real DB session
    container = MagicMock()
    container.settings = E2E_SETTINGS

    # Wire db_session_factory to real testcontainer-backed factory
    container.db_session_factory = session_factory

    # Wire repo factories using real DB sessions
    container.make_tenant_key_repo = lambda session: TenantKeyRepository(session)
    container.make_session_repo = lambda session: SessionRepository(session)
    container.make_tenant_repo = lambda session: TenantRepository(session)

    app.state.container = container

    # Middleware order: last-added = outermost. Auth must run before Tenant.
    # TenantMiddleware added first (inner) → AuthMiddleware added second (outer).
    app.add_middleware(TenantMiddleware)
    app.add_middleware(AuthMiddleware, settings=E2E_SETTINGS)

    app.include_router(tenant_keys.router)
    app.include_router(sessions.router)

    return app


def _make_token(tenant_id: str = TENANT_ID, user_id: str = USER_ID) -> str:
    return create_access_token(user_id, tenant_id, E2E_SETTINGS)


# ---------------------------------------------------------------------------
# Tenant key E2E tests
# ---------------------------------------------------------------------------


class TestTenantKeysE2E:
    """通过 HTTP API 测试租户 API Key 的完整增删改查流程。"""

    @pytest.fixture(scope="class")
    def client(self, e2e_engine):
        sf = create_session_factory(e2e_engine)
        app = _build_e2e_app(sf)
        return TestClient(app, raise_server_exceptions=True)

    @pytest.fixture(autouse=True)
    def _patch_plaintext(self, monkeypatch):
        """Force plaintext mode so tests don't need a real Fernet key."""
        import orchestration.storage.postgres.repos.tenant_key_repo as m
        monkeypatch.setattr(m, "_get_fernet", lambda: None)

    def test_upsert_key_returns_200(self, client: TestClient) -> None:
        """PUT /tenant/keys/{provider_id} with valid data returns 200."""
        token = _make_token()
        resp = client.put(
            "/tenant/keys/anthropic",
            json={"api_key": "sk-test-anthropic-key"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider_id"] == "anthropic"
        assert data["configured"] is True

    def test_upsert_unknown_provider_returns_400(self, client: TestClient) -> None:
        """PUT /tenant/keys/{unknown} returns 400."""
        token = _make_token()
        resp = client.put(
            "/tenant/keys/nonexistent_provider",
            json={"api_key": "sk-x"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    def test_list_keys_shows_configured(self, client: TestClient) -> None:
        """GET /tenant/keys after upsert shows anthropic as configured."""
        token = _make_token()
        # Ensure a key exists
        client.put(
            "/tenant/keys/openai",
            json={"api_key": "sk-openai-e2e"},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = client.get(
            "/tenant/keys",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        keys_by_provider = {k["provider_id"]: k for k in resp.json()["keys"]}
        assert keys_by_provider["openai"]["configured"] is True
        assert "sk-openai" not in keys_by_provider["openai"]["api_key_masked"]

    def test_delete_key_returns_deleted_true(self, client: TestClient) -> None:
        """DELETE /tenant/keys/{provider_id} on existing key returns deleted=true."""
        token = _make_token()
        client.put(
            "/tenant/keys/deepseek",
            json={"api_key": "sk-deepseek-e2e"},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = client.delete(
            "/tenant/keys/deepseek",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_delete_nonexistent_key_returns_deleted_false(self, client: TestClient) -> None:
        """DELETE /tenant/keys/{provider} on nonexistent key returns deleted=false, not 404."""
        token = _make_token()
        resp = client.delete(
            "/tenant/keys/gemini",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["deleted"] is False

    def test_unauthenticated_request_returns_401(self, client: TestClient) -> None:
        """Requests without a valid JWT token return 401."""
        resp = client.get("/tenant/keys")
        assert resp.status_code == 401

    def test_tenant_isolation_in_api(self, e2e_engine) -> None:
        """Tenant A's keys are not visible to Tenant B via the API."""
        import orchestration.storage.postgres.repos.tenant_key_repo as m
        original = m._get_fernet
        m._get_fernet = lambda: None
        try:
            sf = create_session_factory(e2e_engine)
            app = _build_e2e_app(sf)
            client_a = TestClient(app)
            client_b = TestClient(app)

            tenant_a = f"isolation-tenant-a-{uuid.uuid4().hex[:6]}"
            tenant_b = f"isolation-tenant-b-{uuid.uuid4().hex[:6]}"

            token_a = _make_token(tenant_id=tenant_a)
            token_b = _make_token(tenant_id=tenant_b)

            # Tenant A sets anthropic key
            client_a.put(
                "/tenant/keys/anthropic",
                json={"api_key": "sk-only-for-A"},
                headers={"Authorization": f"Bearer {token_a}"},
            )

            # Tenant B should not see the key
            resp_b = client_b.get(
                "/tenant/keys",
                headers={"Authorization": f"Bearer {token_b}"},
            )
            assert resp_b.status_code == 200
            keys_b = {k["provider_id"]: k for k in resp_b.json()["keys"]}
            assert keys_b["anthropic"]["configured"] is False, (
                "Tenant B must not see Tenant A's API key"
            )
        finally:
            m._get_fernet = original


# ---------------------------------------------------------------------------
# Sessions E2E tests
# ---------------------------------------------------------------------------


class TestSessionsE2E:
    """通过 HTTP API 测试会话创建和查询的完整流程。"""

    @pytest.fixture(scope="class")
    def client(self, e2e_engine):
        sf = create_session_factory(e2e_engine)
        app = _build_e2e_app(sf)
        return TestClient(app, raise_server_exceptions=True)

    def test_list_sessions_returns_200(self, client: TestClient) -> None:
        """GET /sessions returns 200 with an empty or populated list."""
        token = _make_token(tenant_id=f"sess-tenant-{uuid.uuid4().hex[:6]}")
        resp = client.get(
            "/sessions",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert "sessions" in resp.json() or isinstance(resp.json(), list)

    def test_get_nonexistent_session_returns_404(self, client: TestClient) -> None:
        """GET /sessions/{nonexistent_id} returns 404."""
        token = _make_token()
        fake_id = str(uuid.uuid4())
        resp = client.get(
            f"/sessions/{fake_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
