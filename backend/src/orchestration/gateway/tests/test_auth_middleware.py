"""
认证中间件单元测试
Auth middleware unit tests.
"""

from __future__ import annotations

import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt

from orchestration.shared.config import Settings
from orchestration.gateway.middleware.auth import AuthMiddleware, create_access_token


# -----------------------------------------------------------------------
# Fixtures / 固定装置
# -----------------------------------------------------------------------


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        JWT_SECRET_KEY="test-secret-key-for-testing-only",
        JWT_ALGORITHM="HS256",
        JWT_EXPIRE_MINUTES=60,
        DATABASE_URL="postgresql+asyncpg://localhost/test",
    )


@pytest.fixture()
def app_with_auth(test_settings: Settings) -> FastAPI:
    """Simple FastAPI app with AuthMiddleware attached."""
    app = FastAPI()
    app.add_middleware(AuthMiddleware, settings=test_settings)

    @app.get("/protected")
    async def protected() -> dict[str, str]:
        return {"ok": "true"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


@pytest.fixture()
def client(app_with_auth: FastAPI) -> TestClient:
    return TestClient(app_with_auth, raise_server_exceptions=False)


# -----------------------------------------------------------------------
# Tests / 测试
# -----------------------------------------------------------------------


def test_health_skips_auth(client: TestClient) -> None:
    """Health endpoint bypasses auth."""
    resp = client.get("/health")
    assert resp.status_code == 200


def test_missing_auth_header_returns_401(client: TestClient) -> None:
    resp = client.get("/protected")
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthorized"


def test_invalid_token_returns_401(client: TestClient) -> None:
    resp = client.get("/protected", headers={"Authorization": "Bearer invalid.token.here"})
    assert resp.status_code == 401


def test_valid_token_passes_through(client: TestClient, test_settings: Settings) -> None:
    token = create_access_token("user-1", "tenant-abc", test_settings)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200


def test_expired_token_returns_401(client: TestClient, test_settings: Settings) -> None:
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    past = now - datetime.timedelta(hours=2)
    claims = {
        "sub": "user-1",
        "tenant_id": "tenant-abc",
        "iat": past,
        "exp": past + datetime.timedelta(minutes=60),
    }
    # Manually create expired token
    expired_token = jwt.encode(claims, test_settings.JWT_SECRET_KEY,
                                algorithm=test_settings.JWT_ALGORITHM)
    resp = client.get("/protected", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401


def test_create_access_token_returns_decodable_jwt(test_settings: Settings) -> None:
    token = create_access_token("alice", "tenant-xyz", test_settings,
                                extra_claims={"role": "admin"})
    payload = jwt.decode(token, test_settings.JWT_SECRET_KEY,
                          algorithms=[test_settings.JWT_ALGORITHM])
    assert payload["sub"] == "alice"
    assert payload["tenant_id"] == "tenant-xyz"
    assert payload["role"] == "admin"


# -----------------------------------------------------------------------
# N-03: /healthz, /readyz, /metrics must bypass auth
# -----------------------------------------------------------------------


@pytest.fixture()
def app_with_skip_paths(test_settings: Settings) -> FastAPI:
    """App with AuthMiddleware + the three probe/metrics endpoints."""
    app = FastAPI()
    app.add_middleware(AuthMiddleware, settings=test_settings)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics() -> dict[str, str]:
        return {"data": "prometheus"}

    return app


def test_healthz_skips_auth(app_with_skip_paths: FastAPI) -> None:
    """GET /healthz must not return 401 without a token (N-03)."""
    client = TestClient(app_with_skip_paths)
    resp = client.get("/healthz")
    assert resp.status_code != 401


def test_readyz_skips_auth(app_with_skip_paths: FastAPI) -> None:
    """GET /readyz must not return 401 without a token (N-03)."""
    client = TestClient(app_with_skip_paths)
    resp = client.get("/readyz")
    assert resp.status_code != 401


def test_metrics_skips_auth(app_with_skip_paths: FastAPI) -> None:
    """GET /metrics must not return 401 without a token (N-03)."""
    client = TestClient(app_with_skip_paths)
    resp = client.get("/metrics")
    assert resp.status_code != 401
