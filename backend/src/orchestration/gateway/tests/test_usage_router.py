"""
用量统计路由单元测试（AsyncMock 所有外部依赖）
Usage router unit tests (all external deps mocked with AsyncMock).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestration.shared.config import Settings
from orchestration.gateway.middleware.auth import create_access_token, AuthMiddleware
from orchestration.gateway.middleware.tenant import TenantMiddleware
from orchestration.gateway.routers import usage


# -----------------------------------------------------------------------
# Test helpers / 测试辅助
# -----------------------------------------------------------------------

TEST_SETTINGS = Settings(
    JWT_SECRET_KEY="test-secret",
    DATABASE_URL="postgresql+asyncpg://localhost/test",
    REDIS_URL="redis://localhost:6379/0",
)


def _make_mock_container(
    aggregated: dict[str, int] | None = None,
) -> MagicMock:
    container = MagicMock()
    container.settings = TEST_SETTINGS

    mock_session = AsyncMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)
    container.db_session_factory = mock_session_factory

    mock_billing_repo = AsyncMock()
    mock_billing_repo.aggregate_by_provider.return_value = aggregated or {}
    container.make_billing_repo.return_value = mock_billing_repo

    return container


def _make_app(container: MagicMock) -> FastAPI:
    app = FastAPI()
    app.add_middleware(TenantMiddleware)
    app.add_middleware(AuthMiddleware, settings=TEST_SETTINGS)
    app.include_router(usage.router)
    app.state.container = container
    return app


def _auth_header(tenant_id: str = "tenant-abc") -> dict[str, str]:
    token = create_access_token("user-1", tenant_id, TEST_SETTINGS)
    return {"Authorization": f"Bearer {token}"}


# -----------------------------------------------------------------------
# GET /usage tests
# -----------------------------------------------------------------------


class TestGetUsage:
    def test_empty_usage_returns_zero(self) -> None:
        container = _make_mock_container(aggregated={})
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/usage", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_tokens"] == 0
        assert data["by_provider"] == []
        assert data["since"] is None

    def test_single_provider_usage(self) -> None:
        container = _make_mock_container(aggregated={"anthropic": 1500})
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/usage", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_tokens"] == 1500
        assert len(data["by_provider"]) == 1
        assert data["by_provider"][0]["provider_id"] == "anthropic"
        assert data["by_provider"][0]["tokens"] == 1500

    def test_multiple_providers_totaled(self) -> None:
        container = _make_mock_container(
            aggregated={"anthropic": 1000, "openai": 500, "deepseek": 250}
        )
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/usage", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_tokens"] == 1750
        assert len(data["by_provider"]) == 3

    def test_providers_sorted_alphabetically(self) -> None:
        container = _make_mock_container(
            aggregated={"openai": 100, "anthropic": 200, "deepseek": 50}
        )
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/usage", headers=_auth_header())
        assert resp.status_code == 200
        ids = [p["provider_id"] for p in resp.json()["by_provider"]]
        assert ids == sorted(ids)

    def test_since_param_passed_to_repo(self) -> None:
        container = _make_mock_container(aggregated={"anthropic": 300})
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get(
            "/usage",
            params={"since": "2025-01-01T00:00:00"},
            headers=_auth_header(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["since"] == "2025-01-01T00:00:00"

        # Verify billing_repo received a datetime argument
        billing_repo = container.make_billing_repo.return_value
        call_kwargs = billing_repo.aggregate_by_provider.call_args.kwargs
        assert call_kwargs.get("since") is not None

    def test_invalid_since_param_ignored(self) -> None:
        container = _make_mock_container(aggregated={})
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        # Invalid datetime string — should not crash, since_dt defaults to None
        resp = client.get(
            "/usage",
            params={"since": "not-a-date"},
            headers=_auth_header(),
        )
        assert resp.status_code == 200

    def test_usage_requires_auth(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/usage")
        assert resp.status_code == 401

    def test_tenant_id_passed_to_repo(self) -> None:
        container = _make_mock_container(aggregated={"gemini": 400})
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        token = create_access_token("user-2", "tenant-xyz", TEST_SETTINGS)
        resp = client.get("/usage", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

        billing_repo = container.make_billing_repo.return_value
        call_kwargs = billing_repo.aggregate_by_provider.call_args.kwargs
        assert call_kwargs.get("tenant_id") == "tenant-xyz" or (
            billing_repo.aggregate_by_provider.call_args.args
            and billing_repo.aggregate_by_provider.call_args.args[0] == "tenant-xyz"
        )
