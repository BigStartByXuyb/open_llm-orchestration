"""
EmbeddingRepository 单元测试（AsyncMock AsyncSession）
Unit tests for EmbeddingRepository (AsyncMock AsyncSession).
"""

from __future__ import annotations

import math
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestration.storage.vector.vector_store import EmbeddingRepository, RAGRetriever, _cosine_similarity
from orchestration.storage.postgres.models import DocumentEmbeddingRow


TENANT_ID = uuid.uuid4()


# -----------------------------------------------------------------------
# _cosine_similarity helper tests
# -----------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors(self) -> None:
        v = [1.0, 0.0, 0.0]
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert _cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero(self) -> None:
        assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_empty_vectors_returns_zero(self) -> None:
        assert _cosine_similarity([], []) == 0.0

    def test_mismatched_lengths_returns_zero(self) -> None:
        assert _cosine_similarity([1.0], [1.0, 2.0]) == 0.0

    def test_normalized_vectors(self) -> None:
        # Two 45-degree vectors should have cos(45°) = √2/2
        a = [1.0, 0.0]
        b = [1.0, 1.0]
        expected = 1.0 / math.sqrt(2)
        assert _cosine_similarity(a, b) == pytest.approx(expected, rel=1e-5)


# -----------------------------------------------------------------------
# Test helpers
# -----------------------------------------------------------------------


def _make_session(
    existing_row: DocumentEmbeddingRow | None = None,
    all_rows: list[DocumentEmbeddingRow] | None = None,
) -> AsyncMock:
    """Build a mock AsyncSession."""
    session = AsyncMock()

    # Mock scalars().all() for search / count queries
    def _make_scalars(rows: list) -> MagicMock:
        mock = MagicMock()
        mock.all.return_value = rows
        mock.scalar_one_or_none.return_value = existing_row
        return mock

    query_result = MagicMock()
    query_result.scalars.return_value = _make_scalars(all_rows or [])
    query_result.scalar_one_or_none.return_value = existing_row
    session.execute.return_value = query_result
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


def _make_row(
    doc_id: str = "doc-1",
    content: str = "Hello world",
    embedding: list[float] | None = None,
) -> DocumentEmbeddingRow:
    row = DocumentEmbeddingRow()
    row.id = uuid.uuid4()
    row.tenant_id = TENANT_ID
    row.doc_id = doc_id
    row.content = content
    row.embedding = embedding or [1.0, 0.0, 0.0]
    row.doc_metadata = {}
    return row


# -----------------------------------------------------------------------
# TestUpsertDocument
# -----------------------------------------------------------------------


class TestUpsertDocument:
    @pytest.mark.asyncio
    async def test_insert_new_document(self) -> None:
        session = _make_session(existing_row=None)
        repo = EmbeddingRepository(session)

        row = await repo.upsert_document(
            tenant_id=TENANT_ID,
            doc_id="doc-new",
            content="New content",
            embedding=[0.5, 0.5, 0.0],
        )

        session.add.assert_called_once()
        session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_existing_document(self) -> None:
        existing = _make_row(doc_id="doc-1", content="Old content", embedding=[1.0, 0.0])
        session = _make_session(existing_row=existing)
        repo = EmbeddingRepository(session)

        await repo.upsert_document(
            tenant_id=TENANT_ID,
            doc_id="doc-1",
            content="Updated content",
            embedding=[0.0, 1.0],
        )

        # existing row should be mutated in-place, not re-added
        session.add.assert_not_called()
        assert existing.content == "Updated content"
        assert existing.embedding == [0.0, 1.0]

    @pytest.mark.asyncio
    async def test_metadata_stored(self) -> None:
        session = _make_session(existing_row=None)
        repo = EmbeddingRepository(session)

        await repo.upsert_document(
            tenant_id=TENANT_ID,
            doc_id="doc-meta",
            content="content",
            embedding=[1.0],
            metadata={"source": "pdf", "page": 3},
        )
        # Verify that the row added to session has the metadata
        added_row: DocumentEmbeddingRow = session.add.call_args[0][0]
        assert added_row.doc_metadata == {"source": "pdf", "page": 3}


# -----------------------------------------------------------------------
# TestSearch
# -----------------------------------------------------------------------


class TestSearch:
    @pytest.mark.asyncio
    async def test_returns_top_k_by_similarity(self) -> None:
        rows = [
            _make_row("d1", embedding=[1.0, 0.0, 0.0]),  # sim=1.0 with query
            _make_row("d2", embedding=[0.0, 1.0, 0.0]),  # sim=0.0 with query
            _make_row("d3", embedding=[0.7, 0.7, 0.0]),  # sim≈0.71 with query
        ]
        session = _make_session(all_rows=rows)
        repo = EmbeddingRepository(session)

        results = await repo.search(
            tenant_id=TENANT_ID,
            query_embedding=[1.0, 0.0, 0.0],
            top_k=2,
        )

        assert len(results) == 2
        assert results[0][0].doc_id == "d1"  # highest similarity first
        assert results[0][1] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_min_score_filters_results(self) -> None:
        rows = [
            _make_row("d1", embedding=[1.0, 0.0]),   # sim=1.0
            _make_row("d2", embedding=[0.0, 1.0]),   # sim=0.0
        ]
        session = _make_session(all_rows=rows)
        repo = EmbeddingRepository(session)

        results = await repo.search(
            tenant_id=TENANT_ID,
            query_embedding=[1.0, 0.0],
            min_score=0.5,
        )

        assert len(results) == 1
        assert results[0][0].doc_id == "d1"

    @pytest.mark.asyncio
    async def test_empty_store_returns_empty_list(self) -> None:
        session = _make_session(all_rows=[])
        repo = EmbeddingRepository(session)

        results = await repo.search(TENANT_ID, [1.0, 0.0])
        assert results == []


# -----------------------------------------------------------------------
# TestDeleteDocument
# -----------------------------------------------------------------------


class TestDeleteDocument:
    @pytest.mark.asyncio
    async def test_delete_existing_returns_true(self) -> None:
        session = _make_session()
        # Simulate rowcount=1 from DELETE
        delete_result = MagicMock()
        delete_result.rowcount = 1
        session.execute.return_value = delete_result

        repo = EmbeddingRepository(session)
        deleted = await repo.delete_document(TENANT_ID, "doc-1")
        assert deleted is True

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self) -> None:
        session = _make_session()
        delete_result = MagicMock()
        delete_result.rowcount = 0
        session.execute.return_value = delete_result

        repo = EmbeddingRepository(session)
        deleted = await repo.delete_document(TENANT_ID, "nonexistent")
        assert deleted is False


# -----------------------------------------------------------------------
# TestRetrieveRelevant ★ Sprint 15
# -----------------------------------------------------------------------


class TestRetrieveRelevant:
    @pytest.mark.asyncio
    async def test_returns_matching_docs(self) -> None:
        rows = [
            _make_row("d1", content="Python tutorial for beginners"),
            _make_row("d2", content="Advanced machine learning"),
        ]
        session = _make_session(all_rows=rows)
        repo = EmbeddingRepository(session)

        results = await repo.retrieve_relevant(TENANT_ID, query="Python", top_k=5)

        assert len(results) == 2
        assert results[0] == ("d1", "Python tutorial for beginners")
        assert results[1] == ("d2", "Advanced machine learning")

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self) -> None:
        session = _make_session(all_rows=[])
        repo = EmbeddingRepository(session)

        results = await repo.retrieve_relevant(TENANT_ID, query="", top_k=5)
        assert results == []
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_whitespace_only_query_returns_empty(self) -> None:
        session = _make_session(all_rows=[])
        repo = EmbeddingRepository(session)

        results = await repo.retrieve_relevant(TENANT_ID, query="   ", top_k=5)
        assert results == []
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_store_returns_empty(self) -> None:
        session = _make_session(all_rows=[])
        repo = EmbeddingRepository(session)

        results = await repo.retrieve_relevant(TENANT_ID, query="Python", top_k=5)
        assert results == []


# -----------------------------------------------------------------------
# TestRAGRetriever ★ Sprint 15
# -----------------------------------------------------------------------


class TestRAGRetriever:
    @pytest.mark.asyncio
    async def test_retriever_uses_session_factory(self) -> None:
        rows = [_make_row("d1", content="Hello world")]
        session = _make_session(all_rows=rows)

        # Build a mock session factory that returns a context manager yielding the session
        mock_factory = MagicMock()
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=session)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_factory.return_value = mock_cm

        retriever = RAGRetriever(mock_factory)
        results = await retriever.retrieve_relevant(TENANT_ID, query="Hello", top_k=3)

        mock_factory.assert_called_once()
        assert len(results) == 1
        assert results[0] == ("d1", "Hello world")
