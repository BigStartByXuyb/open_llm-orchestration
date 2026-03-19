"""
Webhook 路由单元测试（AsyncMock 所有外部依赖）
Webhook router unit tests (all external deps mocked with AsyncMock).
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
from orchestration.gateway.routers import webhooks


# -----------------------------------------------------------------------
# Test helpers / 测试辅助
# -----------------------------------------------------------------------

TEST_SETTINGS = Settings(
    JWT_SECRET_KEY="test-secret",
    DATABASE_URL="postgresql+asyncpg://localhost/test",
    REDIS_URL="redis://localhost:6379/0",
    WEBHOOK_SECRET="",  # no secret by default
)

TEST_SETTINGS_WITH_SECRET = Settings(
    JWT_SECRET_KEY="test-secret",
    DATABASE_URL="postgresql+asyncpg://localhost/test",
    REDIS_URL="redis://localhost:6379/0",
    WEBHOOK_SECRET="super-secret-value",
)


def _make_mock_container() -> MagicMock:
    container = MagicMock()
    container.settings = TEST_SETTINGS

    mock_session = AsyncMock()
    mock_session_factory = MagicMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)
    container.db_session_factory = mock_session_factory

    mock_task_row = MagicMock()
    mock_task_row.task_id = uuid.uuid4()
    mock_task_repo = AsyncMock()
    mock_task_repo.create.return_value = mock_task_row
    container.make_task_repo.return_value = mock_task_repo

    mock_sess_row = MagicMock()
    mock_sess_row.session_id = uuid.uuid4()
    mock_session_repo = AsyncMock()
    mock_session_repo.create.return_value = mock_sess_row
    container.make_session_repo.return_value = mock_session_repo

    mock_state = AsyncMock()
    mock_state.set_status = AsyncMock()
    container.make_task_state_store.return_value = mock_state

    return container


def _make_app(container: MagicMock) -> FastAPI:
    app = FastAPI()
    app.add_middleware(TenantMiddleware)
    app.add_middleware(AuthMiddleware, settings=TEST_SETTINGS)
    app.include_router(webhooks.router)
    app.state.container = container
    return app


def _auth_header(tenant_id: str = "tenant-abc") -> dict[str, str]:
    token = create_access_token("user-1", tenant_id, TEST_SETTINGS)
    return {"Authorization": f"Bearer {token}"}


# -----------------------------------------------------------------------
# POST /webhooks/{event_type} tests
# -----------------------------------------------------------------------


class TestReceiveWebhook:
    def test_basic_webhook_creates_task(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "orchestration.gateway.routers.webhooks.get_settings",
            return_value=TEST_SETTINGS,
        ):
            resp = client.post(
                "/webhooks/github_push",
                json={"message": "Deploy triggered"},
                headers=_auth_header(),
            )

        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == TaskStatus.PENDING
        assert data["event_type"] == "github_push"
        assert "task_id" in data
        assert "session_id" in data

    def test_empty_body_uses_default_message(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "orchestration.gateway.routers.webhooks.get_settings",
            return_value=TEST_SETTINGS,
        ):
            resp = client.post(
                "/webhooks/alert",
                content=b"",
                headers={**_auth_header(), "Content-Type": "application/json"},
            )

        # Empty body should not crash; default message used
        assert resp.status_code == 202
        data = resp.json()
        assert data["event_type"] == "alert"

    def test_webhook_passes_metadata_to_task(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "orchestration.gateway.routers.webhooks.get_settings",
            return_value=TEST_SETTINGS,
        ):
            resp = client.post(
                "/webhooks/custom",
                json={"message": "test", "metadata": {"repo": "my-repo", "branch": "main"}},
                headers=_auth_header(),
            )

        assert resp.status_code == 202
        task_repo = container.make_task_repo.return_value
        call_kwargs = task_repo.create.call_args.kwargs
        assert call_kwargs["input_data"]["metadata"]["repo"] == "my-repo"
        assert call_kwargs["input_data"]["metadata"]["source"] == "webhook"

    def test_webhook_401_without_auth_token(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post("/webhooks/test", json={"message": "hi"})
        assert resp.status_code == 401

    def test_webhook_secret_accepted_when_correct(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "orchestration.gateway.routers.webhooks.get_settings",
            return_value=TEST_SETTINGS_WITH_SECRET,
        ):
            resp = client.post(
                "/webhooks/secure_event",
                json={"message": "ok"},
                headers={
                    **_auth_header(),
                    "X-Webhook-Secret": "super-secret-value",
                },
            )

        assert resp.status_code == 202

    def test_webhook_secret_rejected_when_wrong(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "orchestration.gateway.routers.webhooks.get_settings",
            return_value=TEST_SETTINGS_WITH_SECRET,
        ):
            resp = client.post(
                "/webhooks/secure_event",
                json={"message": "ok"},
                headers={
                    **_auth_header(),
                    "X-Webhook-Secret": "wrong-secret",
                },
            )

        assert resp.status_code == 401

    def test_webhook_secret_rejected_when_missing(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "orchestration.gateway.routers.webhooks.get_settings",
            return_value=TEST_SETTINGS_WITH_SECRET,
        ):
            resp = client.post(
                "/webhooks/secure_event",
                json={"message": "ok"},
                headers=_auth_header(),  # no X-Webhook-Secret
            )

        assert resp.status_code == 401

    def test_no_secret_required_when_not_configured(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "orchestration.gateway.routers.webhooks.get_settings",
            return_value=TEST_SETTINGS,  # WEBHOOK_SECRET=""
        ):
            resp = client.post(
                "/webhooks/open_event",
                json={"message": "no secret needed"},
                headers=_auth_header(),
            )

        assert resp.status_code == 202

    def test_event_type_injected_into_metadata(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        with patch(
            "orchestration.gateway.routers.webhooks.get_settings",
            return_value=TEST_SETTINGS,
        ):
            resp = client.post(
                "/webhooks/my_event",
                json={"message": "trigger"},
                headers=_auth_header(),
            )

        assert resp.status_code == 202
        task_repo = container.make_task_repo.return_value
        meta = task_repo.create.call_args.kwargs["input_data"]["metadata"]
        assert meta["event_type"] == "my_event"
        assert meta["source"] == "webhook"
