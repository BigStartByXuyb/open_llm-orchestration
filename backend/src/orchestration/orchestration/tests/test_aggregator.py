"""
ResultAggregator 单元测试
Unit tests for ResultAggregator — coordinator adapter and transformer are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestration.shared.config import Settings
from orchestration.shared.enums import ProviderID, Role
from orchestration.shared.types import (
    CanonicalMessage,
    ProviderResult,
    RunContext,
    StreamChunk,
    TextPart,
)
from orchestration.orchestration.aggregator import ResultAggregator


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ctx() -> RunContext:
    return RunContext(tenant_id="t1", session_id="s1", task_id="tk1")


def _user_msg(text: str) -> CanonicalMessage:
    return CanonicalMessage(role=Role.USER, content=[TextPart(text=text)])


def _result(subtask_id: str, content: str) -> ProviderResult:
    return ProviderResult(
        subtask_id=subtask_id,
        provider_id=ProviderID.ANTHROPIC,
        content=content,
        transformer_version="v3",
    )


async def _mock_stream(*chunks: str):
    """Helper: async generator yielding StreamChunks."""
    for c in chunks:
        yield StreamChunk(delta=c)


def _make_aggregator(
    stream_chunks: list[str],
    compress_response: str = "compressed",
    settings: Settings | None = None,
) -> ResultAggregator:
    """Build aggregator with mocked adapter + transformer."""
    adapter = AsyncMock()
    # For call() used in level-2 compression
    adapter.call = AsyncMock(return_value={"raw": "data"})
    # For stream() used in final summary — must be a regular function returning async gen
    adapter.stream = lambda *args, **kwargs: _mock_stream(*stream_chunks)

    transformer = MagicMock()
    transformer.transform = MagicMock(return_value={"messages": []})
    transformer.parse_response = MagicMock(
        return_value=ProviderResult(
            subtask_id="",
            provider_id=ProviderID.ANTHROPIC,
            content=compress_response,
        )
    )

    return ResultAggregator(
        coordinator_adapter=adapter,
        coordinator_transformer=transformer,
        settings=settings or Settings(),
    )


# ---------------------------------------------------------------------------
# Basic aggregation
# ---------------------------------------------------------------------------


class TestAggregate:
    @pytest.mark.asyncio
    async def test_aggregate_returns_full_summary(self, ctx: RunContext) -> None:
        agg = _make_aggregator(stream_chunks=["Hello", " world"])
        results = [_result("st_1", "some content")]
        summary = await agg.aggregate(results, _user_msg("question"), [], ctx)
        assert summary == "Hello world"

    @pytest.mark.asyncio
    async def test_aggregate_calls_on_summary_chunk(self, ctx: RunContext) -> None:
        agg = _make_aggregator(stream_chunks=["chunk1", "chunk2"])
        received: list[str] = []

        async def on_chunk(delta: str) -> None:
            received.append(delta)

        await agg.aggregate([_result("st_1", "x")], _user_msg("q"), [], ctx, on_chunk)
        assert received == ["chunk1", "chunk2"]

    @pytest.mark.asyncio
    async def test_aggregate_without_callback_runs_cleanly(
        self, ctx: RunContext
    ) -> None:
        agg = _make_aggregator(stream_chunks=["text"])
        summary = await agg.aggregate([_result("st_1", "r")], _user_msg("q"), [], ctx)
        assert summary == "text"

    @pytest.mark.asyncio
    async def test_transformer_transform_called_with_summary_messages(
        self, ctx: RunContext
    ) -> None:
        adapter = AsyncMock()
        adapter.call = AsyncMock(return_value={})
        adapter.stream = lambda *a, **k: _mock_stream("done")

        transformer = MagicMock()
        transformer.transform = MagicMock(return_value={})
        transformer.parse_response = MagicMock(
            return_value=ProviderResult("", ProviderID.ANTHROPIC, "x")
        )

        agg = ResultAggregator(adapter, transformer)
        await agg.aggregate([_result("st_1", "content")], _user_msg("q"), [], ctx)

        transformer.transform.assert_called_once()
        messages_arg = transformer.transform.call_args[0][0]
        # First message is system prompt, last is synthesis prompt
        assert messages_arg[0].role == Role.SYSTEM
        assert messages_arg[-1].role == Role.USER

    @pytest.mark.asyncio
    async def test_history_included_in_summary_messages(
        self, ctx: RunContext
    ) -> None:
        adapter = AsyncMock()
        adapter.call = AsyncMock(return_value={})
        adapter.stream = lambda *a, **k: _mock_stream("ok")

        transformer = MagicMock()
        transformer.transform = MagicMock(return_value={})
        transformer.parse_response = MagicMock(
            return_value=ProviderResult("", ProviderID.ANTHROPIC, "x")
        )

        agg = ResultAggregator(adapter, transformer)
        history = [_user_msg("old message")]
        await agg.aggregate([_result("st_1", "r")], _user_msg("q"), history, ctx)

        messages_arg = transformer.transform.call_args[0][0]
        # system + 1 history + synthesis = 3
        assert len(messages_arg) == 3


# ---------------------------------------------------------------------------
# Level 1 compression: per-block truncation
# ---------------------------------------------------------------------------


class TestLevel1Compression:
    @pytest.mark.asyncio
    async def test_long_result_truncated(self, ctx: RunContext) -> None:
        settings = Settings(MAX_RESULT_CHARS_PER_BLOCK=10)
        agg = _make_aggregator(stream_chunks=["ok"], settings=settings)

        # 50 chars content > 10 char limit
        results = [_result("st_1", "a" * 50)]
        agg._adapter = AsyncMock()
        agg._adapter.call = AsyncMock(return_value={})
        agg._adapter.stream = lambda *a, **k: _mock_stream("ok")
        agg._transformer = MagicMock()
        agg._transformer.transform = MagicMock(return_value={})
        agg._transformer.parse_response = MagicMock(
            return_value=ProviderResult("", ProviderID.ANTHROPIC, "compressed")
        )

        # Build messages to inspect
        compressed = await agg._compress_results(results, ctx)
        assert len(compressed[0].content) <= 10 + len(" [已截断 / truncated]")
        assert "[已截断 / truncated]" in compressed[0].content

    @pytest.mark.asyncio
    async def test_short_result_not_truncated(self, ctx: RunContext) -> None:
        settings = Settings(MAX_RESULT_CHARS_PER_BLOCK=1000)
        agg = _make_aggregator(stream_chunks=["ok"], settings=settings)
        agg._settings = settings

        results = [_result("st_1", "short")]
        compressed = await agg._compress_results(results, ctx)
        assert compressed[0].content == "short"


# ---------------------------------------------------------------------------
# Level 2 compression: total overflow
# ---------------------------------------------------------------------------


class TestLevel2Compression:
    @pytest.mark.asyncio
    async def test_total_overflow_triggers_per_block_summary(
        self, ctx: RunContext
    ) -> None:
        settings = Settings(
            MAX_RESULT_CHARS_PER_BLOCK=1000,
            MAX_SUMMARY_INPUT_CHARS=5,  # very small threshold
        )

        adapter = AsyncMock()
        adapter.call = AsyncMock(return_value={"raw": "data"})
        adapter.stream = lambda *a, **k: _mock_stream("final")

        transformer = MagicMock()
        transformer.transform = MagicMock(return_value={})
        transformer.parse_response = MagicMock(
            return_value=ProviderResult("", ProviderID.ANTHROPIC, "one sentence summary")
        )

        agg = ResultAggregator(adapter, transformer, settings)
        results = [
            _result("st_1", "first result"),
            _result("st_2", "second result"),
        ]
        compressed = await agg._compress_results(results, ctx)
        # Each block compressed to "one sentence summary"
        assert compressed[0].content == "one sentence summary"
        assert compressed[1].content == "one sentence summary"

    @pytest.mark.asyncio
    async def test_level2_compression_failure_fallbacks_to_500_chars(
        self, ctx: RunContext
    ) -> None:
        settings = Settings(
            MAX_RESULT_CHARS_PER_BLOCK=1000,
            MAX_SUMMARY_INPUT_CHARS=5,
        )

        adapter = AsyncMock()
        adapter.call = AsyncMock(side_effect=RuntimeError("LLM error"))
        adapter.stream = lambda *a, **k: _mock_stream("final")

        transformer = MagicMock()
        transformer.transform = MagicMock(return_value={})

        agg = ResultAggregator(adapter, transformer, settings)
        content = "x" * 600  # 600 chars — should be truncated to 500
        results = [_result("st_1", content)]
        compressed = await agg._compress_results(results, ctx)
        assert len(compressed[0].content) == 500

    @pytest.mark.asyncio
    async def test_no_compression_when_within_total_limit(
        self, ctx: RunContext
    ) -> None:
        settings = Settings(
            MAX_RESULT_CHARS_PER_BLOCK=1000,
            MAX_SUMMARY_INPUT_CHARS=10000,
        )
        agg = _make_aggregator(stream_chunks=["ok"], settings=settings)

        results = [_result("st_1", "short"), _result("st_2", "also short")]
        compressed = await agg._compress_results(results, ctx)
        assert compressed[0].content == "short"
        assert compressed[1].content == "also short"


# ---------------------------------------------------------------------------
# _build_summary_messages
# ---------------------------------------------------------------------------


class TestBuildSummaryMessages:
    def _agg(self) -> ResultAggregator:
        return ResultAggregator(AsyncMock(), MagicMock())

    def test_system_message_is_first(self) -> None:
        agg = self._agg()
        msgs = agg._build_summary_messages(
            [_result("st_1", "r")], _user_msg("q"), []
        )
        assert msgs[0].role == Role.SYSTEM

    def test_synthesis_prompt_is_last(self) -> None:
        agg = self._agg()
        msgs = agg._build_summary_messages(
            [_result("st_1", "r")], _user_msg("q"), []
        )
        assert msgs[-1].role == Role.USER
        text = msgs[-1].content[0].text  # type: ignore[attr-defined]
        assert "synthesis" in text.lower() or "comprehensive" in text.lower()

    def test_result_content_in_synthesis_prompt(self) -> None:
        agg = self._agg()
        msgs = agg._build_summary_messages(
            [_result("st_1", "magical result content")], _user_msg("q"), []
        )
        synthesis_text = msgs[-1].content[0].text  # type: ignore[attr-defined]
        assert "magical result content" in synthesis_text

    def test_original_request_in_synthesis_prompt(self) -> None:
        agg = self._agg()
        msgs = agg._build_summary_messages(
            [_result("st_1", "r")], _user_msg("what is the capital of France?"), []
        )
        synthesis_text = msgs[-1].content[0].text  # type: ignore[attr-defined]
        assert "what is the capital of France?" in synthesis_text
