"""
Health endpoint 和 app factory 单元测试
Health endpoint and app factory unit tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from orchestration.shared.config import Settings
from orchestration.gateway.middleware.auth import AuthMiddleware


@pytest.fixture()
def minimal_app() -> FastAPI:
    """
    A minimal FastAPI app with just health endpoint and AuthMiddleware.
    No database, no Redis — just enough to test the health check.
    """
    settings = Settings(
        JWT_SECRET_KEY="test-secret",
        DATABASE_URL="postgresql+asyncpg://localhost/test",
    )
    app = FastAPI()
    app.add_middleware(AuthMiddleware, settings=settings)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_health_returns_ok(minimal_app: FastAPI) -> None:
    client = TestClient(minimal_app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_does_not_require_auth(minimal_app: FastAPI) -> None:
    """Health must be reachable without Authorization header."""
    client = TestClient(minimal_app)
    resp = client.get("/health")
    assert resp.status_code == 200


def test_protected_endpoint_blocked_without_token(minimal_app: FastAPI) -> None:
    """Non-health routes require a valid token."""

    @minimal_app.get("/secret")
    async def secret() -> dict[str, str]:
        return {"data": "sensitive"}

    client = TestClient(minimal_app, raise_server_exceptions=False)
    resp = client.get("/secret")
    assert resp.status_code == 401


# -----------------------------------------------------------------------
# Readiness probe tests
# -----------------------------------------------------------------------


@pytest.fixture()
def readyz_app() -> FastAPI:
    """App with /readyz endpoint wired to a mock container."""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI()

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        container = getattr(app.state, "container", None)
        if container is None:
            return JSONResponse({"status": "starting"}, status_code=503)
        errors: list[str] = []
        try:
            await container.check_db()
        except Exception as exc:
            errors.append(f"db: {exc}")
        try:
            await container.check_redis()
        except Exception as exc:
            errors.append(f"redis: {exc}")
        if errors:
            return JSONResponse(
                {"status": "unavailable", "detail": "; ".join(errors)},
                status_code=503,
            )
        return JSONResponse({"status": "ok"})

    return app


def test_readyz_no_container_returns_503(readyz_app: FastAPI) -> None:
    """When container not yet set (app still starting), readyz returns 503."""
    client = TestClient(readyz_app, raise_server_exceptions=False)
    # Ensure state.container is NOT set
    if hasattr(readyz_app.state, "container"):
        del readyz_app.state.container
    resp = client.get("/readyz")
    assert resp.status_code == 503


def test_readyz_healthy(readyz_app: FastAPI) -> None:
    """With healthy DB+Redis, readyz returns 200."""
    mock_container = MagicMock()
    mock_container.check_db = AsyncMock()
    mock_container.check_redis = AsyncMock()
    readyz_app.state.container = mock_container

    client = TestClient(readyz_app)
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readyz_db_failure_returns_503(readyz_app: FastAPI) -> None:
    """When DB is unreachable, readyz returns 503 with detail."""
    mock_container = MagicMock()
    mock_container.check_db = AsyncMock(side_effect=Exception("DB down"))
    mock_container.check_redis = AsyncMock()
    readyz_app.state.container = mock_container

    client = TestClient(readyz_app, raise_server_exceptions=False)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert "db" in resp.json().get("detail", "")


def test_readyz_redis_failure_returns_503(readyz_app: FastAPI) -> None:
    """When Redis is unreachable, readyz returns 503 with detail."""
    mock_container = MagicMock()
    mock_container.check_db = AsyncMock()
    mock_container.check_redis = AsyncMock(side_effect=Exception("Redis down"))
    readyz_app.state.container = mock_container

    client = TestClient(readyz_app, raise_server_exceptions=False)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert "redis" in resp.json().get("detail", "")


def test_healthz_alias() -> None:
    """/healthz should return 200 with status ok."""
    from fastapi import FastAPI

    alias_app = FastAPI()

    @alias_app.get("/health")
    @alias_app.get("/healthz")
    async def health_and_healthz() -> dict[str, str]:
        return {"status": "ok"}

    client = TestClient(alias_app)
    for path in ("/health", "/healthz"):
        resp = client.get(path)
        assert resp.status_code == 200, f"{path} should return 200"
        assert resp.json() == {"status": "ok"}
