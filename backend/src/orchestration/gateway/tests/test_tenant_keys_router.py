"""
租户 API Key 路由单元测试（★ Sprint 15）
Tenant API key router unit tests (all external deps mocked).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestration.shared.config import Settings
from orchestration.gateway.middleware.auth import create_access_token, AuthMiddleware
from orchestration.gateway.middleware.tenant import TenantMiddleware
from orchestration.gateway.routers import tenant_keys
from orchestration.storage.postgres.models import TenantKeyRow


# -----------------------------------------------------------------------
# Test helpers
# -----------------------------------------------------------------------

TEST_SETTINGS = Settings(
    JWT_SECRET_KEY="test-secret",
    DATABASE_URL="postgresql+asyncpg://localhost/test",
    REDIS_URL="redis://localhost:6379/0",
)


def _make_key_row(
    provider_id: str = "anthropic",
    api_key: str = "sk-test-1234567890abcdef",
) -> TenantKeyRow:
    row = TenantKeyRow()
    row.id = uuid.uuid4()
    row.tenant_id = uuid.uuid4()
    row.provider_id = provider_id
    row.api_key = api_key
    return row


def _make_mock_container(
    list_rows: list[TenantKeyRow] | None = None,
    get_row: TenantKeyRow | None = None,
    upsert_row: TenantKeyRow | None = None,
    delete_result: bool = True,
) -> MagicMock:
    container = MagicMock()
    container.settings = TEST_SETTINGS

    mock_session = AsyncMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)
    container.db_session_factory = mock_session_factory

    mock_repo = AsyncMock()
    mock_repo.list_all.return_value = list_rows or []
    mock_repo.get.return_value = get_row
    mock_repo.upsert.return_value = upsert_row or _make_key_row()
    mock_repo.delete.return_value = delete_result
    container.make_tenant_key_repo.return_value = mock_repo

    return container


def _make_app(container: MagicMock) -> FastAPI:
    app = FastAPI()
    app.add_middleware(TenantMiddleware)
    app.add_middleware(AuthMiddleware, settings=TEST_SETTINGS)
    app.include_router(tenant_keys.router)
    app.state.container = container
    return app


def _auth_header(tenant_id: str = "tenant-abc") -> dict[str, str]:
    token = create_access_token("user-1", tenant_id, TEST_SETTINGS)
    return {"Authorization": f"Bearer {token}"}


# -----------------------------------------------------------------------
# GET /tenant/keys tests
# -----------------------------------------------------------------------


class TestListTenantKeys:
    def test_list_empty(self) -> None:
        container = _make_mock_container(list_rows=[])
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/tenant/keys", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert "keys" in data
        # All 6 providers listed, all unconfigured
        assert len(data["keys"]) == 6
        assert all(not k["configured"] for k in data["keys"])

    def test_list_with_configured_key(self) -> None:
        rows = [_make_key_row("anthropic", "sk-anthropic-xyz")]
        container = _make_mock_container(list_rows=rows)
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/tenant/keys", headers=_auth_header())
        assert resp.status_code == 200
        keys = {k["provider_id"]: k for k in resp.json()["keys"]}
        assert keys["anthropic"]["configured"] is True
        # Key should be masked (not show full key)
        assert keys["anthropic"]["api_key_masked"] != "sk-anthropic-xyz"
        assert keys["anthropic"]["api_key_masked"].endswith("-xyz")

    def test_list_requires_auth(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/tenant/keys")
        assert resp.status_code == 401


# -----------------------------------------------------------------------
# PUT /tenant/keys/{provider_id} tests
# -----------------------------------------------------------------------


class TestUpsertTenantKey:
    def test_upsert_valid_provider(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.put(
            "/tenant/keys/openai",
            json={"api_key": "sk-openai-newkey"},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider_id"] == "openai"
        assert data["configured"] is True

    def test_upsert_invalid_provider_returns_400(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.put(
            "/tenant/keys/unknown_provider",
            json={"api_key": "sk-key"},
            headers=_auth_header(),
        )
        assert resp.status_code == 400

    def test_upsert_empty_key_returns_400(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.put(
            "/tenant/keys/anthropic",
            json={"api_key": "   "},
            headers=_auth_header(),
        )
        assert resp.status_code == 400

    def test_upsert_requires_auth(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.put("/tenant/keys/openai", json={"api_key": "sk-key"})
        assert resp.status_code == 401


# -----------------------------------------------------------------------
# DELETE /tenant/keys/{provider_id} tests
# -----------------------------------------------------------------------


class TestDeleteTenantKey:
    def test_delete_existing_returns_deleted_true(self) -> None:
        container = _make_mock_container(delete_result=True)
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.delete("/tenant/keys/anthropic", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert resp.json()["provider_id"] == "anthropic"

    def test_delete_missing_returns_deleted_false(self) -> None:
        container = _make_mock_container(delete_result=False)
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.delete("/tenant/keys/openai", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["deleted"] is False

    def test_delete_requires_auth(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.delete("/tenant/keys/anthropic")
        assert resp.status_code == 401
