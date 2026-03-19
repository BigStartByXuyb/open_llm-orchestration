"""
文档摄入路由单元测试（AsyncMock 所有外部依赖）
Documents router unit tests (all external deps mocked with AsyncMock).
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
from orchestration.gateway.routers import documents
from orchestration.storage.postgres.models import DocumentEmbeddingRow


# -----------------------------------------------------------------------
# Test helpers / 测试辅助
# -----------------------------------------------------------------------

TEST_SETTINGS = Settings(
    JWT_SECRET_KEY="test-secret",
    DATABASE_URL="postgresql+asyncpg://localhost/test",
    REDIS_URL="redis://localhost:6379/0",
)

SAMPLE_EMBEDDING = [0.1, 0.2, 0.3, 0.4]


def _make_doc_row(
    doc_id: str = "doc-1",
    content: str = "Hello world content",
    embedding: list[float] | None = None,
    metadata: dict | None = None,
) -> DocumentEmbeddingRow:
    row = DocumentEmbeddingRow()
    row.id = uuid.uuid4()
    row.tenant_id = uuid.uuid4()
    row.doc_id = doc_id
    row.content = content
    row.embedding = embedding or SAMPLE_EMBEDDING
    row.doc_metadata = metadata or {}
    return row


def _make_mock_container(
    upsert_result: DocumentEmbeddingRow | None = None,
    count: int = 0,
    search_results: list | None = None,
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
    mock_repo.upsert_document.return_value = upsert_result or _make_doc_row()
    mock_repo.count.return_value = count
    mock_repo.search.return_value = search_results or []
    mock_repo.delete_document.return_value = delete_result
    container.make_embedding_repo.return_value = mock_repo

    return container


def _make_app(container: MagicMock) -> FastAPI:
    app = FastAPI()
    app.add_middleware(TenantMiddleware)
    app.add_middleware(AuthMiddleware, settings=TEST_SETTINGS)
    app.include_router(documents.router)
    app.state.container = container
    return app


def _auth_header(tenant_id: str = "tenant-abc") -> dict[str, str]:
    token = create_access_token("user-1", tenant_id, TEST_SETTINGS)
    return {"Authorization": f"Bearer {token}"}


# -----------------------------------------------------------------------
# POST /documents tests
# -----------------------------------------------------------------------


class TestIngestDocument:
    def test_ingest_returns_201(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/documents",
            json={"content": "Test content", "embedding": SAMPLE_EMBEDDING},
            headers=_auth_header(),
        )

        assert resp.status_code == 201
        data = resp.json()
        assert "doc_id" in data
        assert data["content_length"] == len("Test content")

    def test_ingest_with_explicit_doc_id(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/documents",
            json={"doc_id": "my-doc-123", "content": "Hello", "embedding": [0.1, 0.2]},
            headers=_auth_header(),
        )

        assert resp.status_code == 201
        assert resp.json()["doc_id"] == "my-doc-123"

    def test_ingest_with_metadata(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/documents",
            json={
                "content": "Doc with metadata",
                "embedding": [1.0, 0.0],
                "metadata": {"source": "pdf", "page": 5},
            },
            headers=_auth_header(),
        )

        assert resp.status_code == 201
        repo = container.make_embedding_repo.return_value
        call_kwargs = repo.upsert_document.call_args.kwargs
        assert call_kwargs["metadata"]["source"] == "pdf"

    def test_ingest_empty_content_returns_400(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/documents",
            json={"content": "  ", "embedding": [0.1]},
            headers=_auth_header(),
        )

        assert resp.status_code == 400

    def test_ingest_empty_embedding_returns_400(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/documents",
            json={"content": "Hello", "embedding": []},
            headers=_auth_header(),
        )

        assert resp.status_code == 400

    def test_ingest_requires_auth(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/documents",
            json={"content": "Hello", "embedding": [0.1]},
        )
        assert resp.status_code == 401


# -----------------------------------------------------------------------
# GET /documents tests
# -----------------------------------------------------------------------


class TestListDocuments:
    def test_empty_list(self) -> None:
        container = _make_mock_container(count=0)
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/documents", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["documents"] == []
        assert data["total"] == 0

    def test_list_with_documents(self) -> None:
        rows = [
            (_make_doc_row("d1", "Content one"), 0.9),
            (_make_doc_row("d2", "Content two"), 0.8),
        ]
        container = _make_mock_container(count=2, search_results=rows)
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/documents", headers=_auth_header())
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["documents"]) == 2
        assert data["documents"][0]["doc_id"] == "d1"

    def test_list_requires_auth(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/documents")
        assert resp.status_code == 401


# -----------------------------------------------------------------------
# DELETE /documents/{doc_id} tests
# -----------------------------------------------------------------------


class TestDeleteDocument:
    def test_delete_existing_returns_deleted_true(self) -> None:
        container = _make_mock_container(delete_result=True)
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.delete("/documents/doc-1", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert resp.json()["doc_id"] == "doc-1"

    def test_delete_missing_returns_deleted_false(self) -> None:
        container = _make_mock_container(delete_result=False)
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.delete("/documents/nonexistent", headers=_auth_header())
        assert resp.status_code == 200
        assert resp.json()["deleted"] is False

    def test_delete_requires_auth(self) -> None:
        container = _make_mock_container()
        app = _make_app(container)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.delete("/documents/doc-1")
        assert resp.status_code == 401
