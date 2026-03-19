"""
TaskDecomposer RAG 注入单元测试（★ Sprint 15）
Unit tests for TaskDecomposer RAG context enrichment.

验证 doc_retriever 注入后，相关文档是否正确添加到 system prompt。
Verifies that relevant docs are correctly injected into the system prompt when doc_retriever
is provided.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestration.shared.config import Settings
from orchestration.shared.enums import ProviderID
from orchestration.shared.types import (
    CanonicalMessage,
    ProviderResult,
    RunContext,
    TextPart,
    Role,
)
from orchestration.orchestration.decomposer import TaskDecomposer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_PLAN_JSON = json.dumps({
    "summary": "test plan",
    "subtasks": [
        {"subtask_id": "st_1", "description": "do something", "capability": "text", "depends_on": []},
    ],
})


def _make_adapter() -> AsyncMock:
    adapter = AsyncMock()
    adapter.provider_id = ProviderID.ANTHROPIC
    adapter.call = AsyncMock(return_value={"raw": "data"})
    return adapter


def _make_transformer() -> MagicMock:
    transformer = MagicMock()
    transformer.provider_id = ProviderID.ANTHROPIC
    transformer.api_version = "v3"
    transformer.transform = MagicMock(return_value={"messages": []})
    transformer.parse_response = MagicMock(
        return_value=ProviderResult(
            subtask_id="",
            provider_id=ProviderID.ANTHROPIC,
            content=_VALID_PLAN_JSON,
        )
    )
    return transformer


def _make_doc_retriever(docs: list[tuple[str, str]]) -> AsyncMock:
    retriever = AsyncMock()
    retriever.retrieve_relevant = AsyncMock(return_value=docs)
    return retriever


def _user_msg(text: str = "What is Python?") -> CanonicalMessage:
    return CanonicalMessage(role=Role.USER, content=[TextPart(text=text)])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDecomposerRAG:
    @pytest.mark.asyncio
    async def test_rag_docs_injected_into_system_prompt(self) -> None:
        """When doc_retriever returns docs, they appear in the system prompt."""
        adapter = _make_adapter()
        transformer = _make_transformer()
        settings = Settings(RAG_TOP_K=3)
        docs = [("doc-1", "Python is a programming language.")]
        retriever = _make_doc_retriever(docs)

        decomposer = TaskDecomposer(adapter, transformer, settings)
        ctx = RunContext(tenant_id="t1", session_id="s1", task_id="tk1")

        await decomposer.decompose(_user_msg(), [], ctx, doc_retriever=retriever)

        # The transformer.transform should have been called with a system message
        # containing the RAG context
        call_args = transformer.transform.call_args[0][0]  # first positional arg (messages list)
        system_messages = [m for m in call_args if m.role == Role.SYSTEM]
        assert len(system_messages) == 1
        system_text = system_messages[0].content[0].text
        assert "doc-1" in system_text
        assert "Python is a programming language." in system_text

    @pytest.mark.asyncio
    async def test_no_doc_retriever_skips_rag(self) -> None:
        """When doc_retriever is None, the system prompt contains only the base prompt."""
        adapter = _make_adapter()
        transformer = _make_transformer()
        settings = Settings(RAG_TOP_K=3)

        decomposer = TaskDecomposer(adapter, transformer, settings)
        ctx = RunContext(tenant_id="t1", session_id="s1", task_id="tk1")

        await decomposer.decompose(_user_msg(), [], ctx, doc_retriever=None)

        call_args = transformer.transform.call_args[0][0]
        system_messages = [m for m in call_args if m.role == Role.SYSTEM]
        assert len(system_messages) == 1
        system_text = system_messages[0].content[0].text
        # Should NOT contain RAG header
        assert "knowledge base" not in system_text.lower() or "doc:" not in system_text

    @pytest.mark.asyncio
    async def test_rag_top_k_zero_skips_retrieval(self) -> None:
        """When RAG_TOP_K=0, retrieval is skipped even if doc_retriever is provided."""
        adapter = _make_adapter()
        transformer = _make_transformer()
        settings = Settings(RAG_TOP_K=0)
        retriever = _make_doc_retriever([("d1", "some content")])

        decomposer = TaskDecomposer(adapter, transformer, settings)
        ctx = RunContext(tenant_id="t1", session_id="s1", task_id="tk1")

        await decomposer.decompose(_user_msg(), [], ctx, doc_retriever=retriever)

        # retrieve_relevant should NOT have been called
        retriever.retrieve_relevant.assert_not_called()

    @pytest.mark.asyncio
    async def test_rag_retriever_error_is_non_fatal(self) -> None:
        """When doc_retriever raises, decompose continues without RAG context."""
        adapter = _make_adapter()
        transformer = _make_transformer()
        settings = Settings(RAG_TOP_K=3)

        retriever = AsyncMock()
        retriever.retrieve_relevant = AsyncMock(side_effect=RuntimeError("DB down"))

        decomposer = TaskDecomposer(adapter, transformer, settings)
        ctx = RunContext(tenant_id="t1", session_id="s1", task_id="tk1")

        # Should NOT raise even though retriever failed
        plan = await decomposer.decompose(_user_msg(), [], ctx, doc_retriever=retriever)
        assert plan is not None

    @pytest.mark.asyncio
    async def test_rag_empty_query_skips_retrieval(self) -> None:
        """When user message has empty text, retrieval is skipped."""
        adapter = _make_adapter()
        transformer = _make_transformer()
        settings = Settings(RAG_TOP_K=3)
        retriever = _make_doc_retriever([])

        decomposer = TaskDecomposer(adapter, transformer, settings)
        ctx = RunContext(tenant_id="t1", session_id="s1", task_id="tk1")

        # Empty text message
        empty_msg = CanonicalMessage(role=Role.USER, content=[TextPart(text="   ")])
        await decomposer.decompose(empty_msg, [], ctx, doc_retriever=retriever)

        # retrieve_relevant should NOT have been called (empty query)
        retriever.retrieve_relevant.assert_not_called()

    @pytest.mark.asyncio
    async def test_rag_retriever_called_with_tenant_and_query(self) -> None:
        """doc_retriever is called with the correct tenant_id and query text."""
        adapter = _make_adapter()
        transformer = _make_transformer()
        settings = Settings(RAG_TOP_K=5)
        retriever = _make_doc_retriever([])

        decomposer = TaskDecomposer(adapter, transformer, settings)
        ctx = RunContext(tenant_id="tenant-xyz", session_id="s1", task_id="tk1")

        await decomposer.decompose(_user_msg("What is Python?"), [], ctx, doc_retriever=retriever)

        retriever.retrieve_relevant.assert_called_once()
        call_kwargs = retriever.retrieve_relevant.call_args
        assert call_kwargs.kwargs["tenant_id"] == "tenant-xyz"
        assert "Python" in call_kwargs.kwargs["query"]
        assert call_kwargs.kwargs["top_k"] == 5
