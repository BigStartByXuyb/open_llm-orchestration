"""
任务路由单元测试（AsyncMock 所有外部依赖）
Task router unit tests (all external deps mocked with AsyncMock).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestration.shared.config import Settings
from orchestration.shared.enums import TaskStatus
from orchestration.shared.types import RunContext
from orchestration.gateway.middleware.auth import create_access_token, AuthMiddleware
from orchestration.gateway.middleware.tenant import TenantMiddleware
from orchestration.gateway.routers import tasks


# -----------------------------------------------------------------------
# Test helpers / 测试辅助
# -----------------------------------------------------------------------

TEST_SETTINGS = Settings(
    JWT_SECRET_KEY="test-secret",
    DATABASE_URL="postgresql+asyncpg://localhost/test",
    REDIS_URL="redis://localhost:6379/0",
)


def _make_mock_container(
    task_row: MagicMock | None = None,
    session_row: MagicMock | None = None,
) -> MagicMock:
    """Build a mock AppContainer with pre-configured repos and Redis store."""
    container = MagicMock()
    container.settings = TEST_SETTINGS

    # Mock session factory
    mock_session = AsyncMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)
    container.db_session_factory = mock_session_factory

    # Mock repos
    mock_task_repo = AsyncMock()
    if task_row:
        mock_task_repo.get.return_value = task_row
    else:
        mock_task_row = MagicMock()
        mock_task_row.task_id = uuid.uuid4()
        mock_task_row.session_id = uuid.uuid4()
        mock_task_repo.create.return_value = mock_task_row
    container.make_task_repo.return_value = mock_task_repo

    mock_session_repo = AsyncMock()
    if session_row:
        mock_session_repo.get.return_value = session_row
    else:
        mock_sess = MagicMock()
        mock_sess.session_id = uuid.uuid4()
        mock_session_repo.create.return_value = mock_sess
    container.make_session_repo.return_value = mock_session_repo

    # Mock Redis task state store
    mock_state = AsyncMock()
    mock_state.set_status = AsyncMock()
    mock_state.get_status = AsyncMock(return_value=None)
    container.make_task_state_store.return_value = mock_state

    return container


def _make_app(container: MagicMock) -> FastAPI:
    """Minimal app with mocked container in app.state."""
    app = FastAPI()
    app.add_middleware(TenantMiddleware)
    app.add_middleware(AuthMiddleware, settings=TEST_SETTINGS)
    app.include_router(tasks.router)
    app.state.container = container
    return app


# -----------------------------------------------------------------------
# POST /tasks tests
# -----------------------------------------------------------------------


def test_create_task_without_session_id() -> None:
    container = _make_mock_container()
    app = _make_app(container)
    token = create_access_token("user-1", "tenant-abc", TEST_SETTINGS)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/tasks",
        json={"message": "Hello, world!"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == TaskStatus.PENDING
    assert "task_id" in data
    assert "session_id" in data


def test_create_task_returns_401_without_token() -> None:
    container = _make_mock_container()
    app = _make_app(container)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/tasks", json={"message": "hello"})
    assert resp.status_code == 401


def test_create_task_with_existing_session() -> None:
    existing_session = MagicMock()
    existing_session.session_id = uuid.uuid4()

    container = _make_mock_container(session_row=existing_session)
    # Make get() return the existing session
    container.make_session_repo.return_value.get = AsyncMock(return_value=existing_session)

    app = _make_app(container)
    token = create_access_token("user-1", "tenant-abc", TEST_SETTINGS)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/tasks",
        json={"message": "continue here", "session_id": str(existing_session.session_id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 202


def test_create_task_with_nonexistent_session_returns_404() -> None:
    container = _make_mock_container()
    # Session not found
    container.make_session_repo.return_value.get = AsyncMock(return_value=None)

    app = _make_app(container)
    token = create_access_token("user-1", "tenant-abc", TEST_SETTINGS)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/tasks",
        json={"message": "hello", "session_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# -----------------------------------------------------------------------
# GET /tasks/{task_id} tests
# -----------------------------------------------------------------------


def test_get_task_from_redis_cache() -> None:
    container = _make_mock_container()
    container.make_task_state_store.return_value.get_status = AsyncMock(
        return_value={"status": "running", "trace_id": "t1"}
    )
    app = _make_app(container)
    token = create_access_token("user-1", "tenant-abc", TEST_SETTINGS)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        f"/tasks/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"


def test_get_task_from_postgres_when_redis_miss() -> None:
    task_id = uuid.uuid4()
    session_id = uuid.uuid4()
    mock_task = MagicMock()
    mock_task.task_id = task_id
    mock_task.session_id = session_id
    mock_task.status = "done"
    mock_task.result = {"summary": "All done"}
    mock_task.error_message = None

    container = _make_mock_container()
    container.make_task_state_store.return_value.get_status = AsyncMock(return_value=None)
    container.make_task_repo.return_value.get = AsyncMock(return_value=mock_task)

    app = _make_app(container)
    token = create_access_token("user-1", "tenant-abc", TEST_SETTINGS)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        f"/tasks/{task_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert data["result"] == "All done"


def test_get_task_not_found_returns_404() -> None:
    container = _make_mock_container()
    container.make_task_state_store.return_value.get_status = AsyncMock(return_value=None)
    container.make_task_repo.return_value.get = AsyncMock(return_value=None)

    app = _make_app(container)
    token = create_access_token("user-1", "tenant-abc", TEST_SETTINGS)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(
        f"/tasks/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# -----------------------------------------------------------------------
# Sprint 18: GET /tasks/{task_id}/stream SSE tests
# -----------------------------------------------------------------------


def test_stream_task_returns_sse_content_type() -> None:
    """GET /tasks/{task_id}/stream returns text/event-stream content type."""
    container = _make_mock_container()
    # Make task immediately done so the generator terminates
    container.make_task_state_store.return_value.get_status = AsyncMock(
        return_value={"status": "done", "updated_at": "2026-01-01T00:00:00Z", "error": ""}
    )
    container.make_task_state_store.return_value.get_events_after = AsyncMock(return_value=[])

    app = _make_app(container)
    token = create_access_token("user-1", "tenant-abc", TEST_SETTINGS)

    client = TestClient(app, raise_server_exceptions=False)
    task_id = str(uuid.uuid4())
    with client.stream(
        "GET",
        f"/tasks/{task_id}/stream",
        headers={"Authorization": f"Bearer {token}"},
    ) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")


def test_stream_task_emits_status_events() -> None:
    """SSE stream emits at least one 'data:' line with the task status."""
    container = _make_mock_container()
    container.make_task_state_store.return_value.get_status = AsyncMock(
        return_value={"status": "done", "updated_at": "2026-01-01T00:00:00Z", "error": ""}
    )
    container.make_task_state_store.return_value.get_events_after = AsyncMock(return_value=[])

    app = _make_app(container)
    token = create_access_token("user-1", "tenant-abc", TEST_SETTINGS)

    client = TestClient(app, raise_server_exceptions=False)
    task_id = str(uuid.uuid4())
    with client.stream(
        "GET",
        f"/tasks/{task_id}/stream",
        headers={"Authorization": f"Bearer {token}"},
    ) as resp:
        content = b"".join(resp.iter_bytes()).decode()
    assert "data:" in content
    assert "done" in content


def test_stream_task_requires_auth() -> None:
    """SSE stream endpoint requires authentication."""
    container = _make_mock_container()
    app = _make_app(container)

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/tasks/{uuid.uuid4()}/stream")
    assert resp.status_code == 401
