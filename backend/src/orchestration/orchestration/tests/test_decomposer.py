"""
TaskDecomposer 单元测试
Unit tests for TaskDecomposer — all external calls (adapter, transformer) are mocked.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from orchestration.shared.config import Settings
from orchestration.shared.enums import Capability, ProviderID, Role
from orchestration.shared.errors import ProviderError, TransformError
from orchestration.shared.types import (
    CanonicalMessage,
    ProviderResult,
    RunContext,
    TextPart,
)
from orchestration.orchestration.decomposer import TaskDecomposer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ctx() -> RunContext:
    return RunContext(tenant_id="t1", session_id="s1", task_id="tk1")


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        CONTEXT_TRUNCATION_THRESHOLD=1000,  # small for testing
    )


def _make_adapter(response_content: str) -> AsyncMock:
    adapter = AsyncMock()
    adapter.provider_id = ProviderID.ANTHROPIC
    adapter.call = AsyncMock(return_value={"raw": "data"})
    return adapter


def _make_transformer(response_content: str) -> MagicMock:
    transformer = MagicMock()
    transformer.provider_id = ProviderID.ANTHROPIC
    transformer.api_version = "v3"
    transformer.transform = MagicMock(return_value={"messages": []})
    transformer.parse_response = MagicMock(
        return_value=ProviderResult(
            subtask_id="",
            provider_id=ProviderID.ANTHROPIC,
            content=response_content,
        )
    )
    return transformer


def _user_msg(text: str) -> CanonicalMessage:
    return CanonicalMessage(role=Role.USER, content=[TextPart(text=text)])


def _system_msg(text: str) -> CanonicalMessage:
    return CanonicalMessage(role=Role.SYSTEM, content=[TextPart(text=text)])


_VALID_PLAN_JSON = json.dumps(
    {
        "summary": "Do something",
        "subtasks": [
            {
                "subtask_id": "st_1",
                "description": "Write a poem",
                "capability": "text",
                "depends_on": [],
            }
        ],
    }
)


# ---------------------------------------------------------------------------
# Basic decomposition
# ---------------------------------------------------------------------------


class TestDecompose:
    @pytest.mark.asyncio
    async def test_successful_decompose(self, ctx: RunContext, settings: Settings) -> None:
        adapter = _make_adapter(_VALID_PLAN_JSON)
        transformer = _make_transformer(_VALID_PLAN_JSON)
        decomposer = TaskDecomposer(adapter, transformer, settings)

        plan = await decomposer.decompose(_user_msg("Write a poem"), [], ctx)

        assert plan.summary == "Do something"
        assert len(plan.subtasks) == 1
        assert plan.subtasks[0].subtask_id == "st_1"
        assert plan.subtasks[0].capability == Capability.TEXT

    @pytest.mark.asyncio
    async def test_transform_called_with_system_prompt(
        self, ctx: RunContext, settings: Settings
    ) -> None:
        adapter = _make_adapter(_VALID_PLAN_JSON)
        transformer = _make_transformer(_VALID_PLAN_JSON)
        decomposer = TaskDecomposer(adapter, transformer, settings)

        await decomposer.decompose(_user_msg("Hello"), [], ctx)

        transformer.transform.assert_called_once()
        messages_arg = transformer.transform.call_args[0][0]
        # First message should be the system decomposition prompt
        assert messages_arg[0].role == Role.SYSTEM

    @pytest.mark.asyncio
    async def test_history_included_in_messages(
        self, ctx: RunContext, settings: Settings
    ) -> None:
        adapter = _make_adapter(_VALID_PLAN_JSON)
        transformer = _make_transformer(_VALID_PLAN_JSON)
        decomposer = TaskDecomposer(adapter, transformer, settings)

        history = [_user_msg("hi"), _system_msg("hello")]
        await decomposer.decompose(_user_msg("now do this"), history, ctx)

        messages_arg = transformer.transform.call_args[0][0]
        # system prompt + 2 history + 1 user = 4 messages
        assert len(messages_arg) == 4

    @pytest.mark.asyncio
    async def test_multiple_subtasks(self, ctx: RunContext, settings: Settings) -> None:
        plan_json = json.dumps(
            {
                "summary": "Multi-step plan",
                "subtasks": [
                    {
                        "subtask_id": "st_1",
                        "description": "Search",
                        "capability": "search",
                        "depends_on": [],
                    },
                    {
                        "subtask_id": "st_2",
                        "description": "Analyze",
                        "capability": "analysis",
                        "depends_on": ["st_1"],
                    },
                ],
            }
        )
        adapter = _make_adapter(plan_json)
        transformer = _make_transformer(plan_json)
        decomposer = TaskDecomposer(adapter, transformer, settings)

        plan = await decomposer.decompose(_user_msg("research topic"), [], ctx)

        assert len(plan.subtasks) == 2
        assert plan.subtasks[0].capability == Capability.SEARCH
        assert plan.subtasks[1].capability == Capability.ANALYSIS
        assert plan.subtasks[1].depends_on == ["st_1"]


# ---------------------------------------------------------------------------
# Context truncation
# ---------------------------------------------------------------------------


class TestContextTruncation:
    @pytest.mark.asyncio
    async def test_sliding_window_applied_above_80_percent(
        self, ctx: RunContext
    ) -> None:
        # threshold=100, 80%=80 chars: create history exceeding 80 chars
        settings = Settings(CONTEXT_TRUNCATION_THRESHOLD=100)
        adapter = _make_adapter(_VALID_PLAN_JSON)
        transformer = _make_transformer(_VALID_PLAN_JSON)
        decomposer = TaskDecomposer(adapter, transformer, settings)

        # Each message is ~30 chars; 3 history + 1 user = ~120 chars total
        history = [_user_msg("a" * 30), _user_msg("b" * 30), _user_msg("c" * 30)]
        user_msg = _user_msg("d" * 30)

        await decomposer.decompose(user_msg, history, ctx)

        # Messages passed to transformer should be fewer than 5 (4 + system)
        messages_arg = transformer.transform.call_args[0][0]
        assert len(messages_arg) < 5  # sliding window reduced the history

    @pytest.mark.asyncio
    async def test_summary_compression_applied_above_95_percent(
        self, ctx: RunContext
    ) -> None:
        # threshold=100, 95%=95 chars: create history exceeding 95 chars
        settings = Settings(CONTEXT_TRUNCATION_THRESHOLD=100)
        adapter = _make_adapter(_VALID_PLAN_JSON)
        transformer = _make_transformer(_VALID_PLAN_JSON)
        # First parse_response for compression summary, second for task plan
        transformer.parse_response = MagicMock(
            side_effect=[
                ProviderResult(
                    subtask_id="",
                    provider_id=ProviderID.ANTHROPIC,
                    content="Summary of history",
                ),
                ProviderResult(
                    subtask_id="",
                    provider_id=ProviderID.ANTHROPIC,
                    content=_VALID_PLAN_JSON,
                ),
            ]
        )
        decomposer = TaskDecomposer(adapter, transformer, settings)

        # Create 4 messages of 30 chars each = 120 chars > 95 chars
        history = [_user_msg("a" * 30), _user_msg("b" * 30), _user_msg("c" * 30)]
        user_msg = _user_msg("d" * 30)

        plan = await decomposer.decompose(user_msg, history, ctx)
        assert plan.summary == "Do something"

        # adapter.call should be called twice: once for compression, once for decompose
        assert adapter.call.call_count == 2

    @pytest.mark.asyncio
    async def test_summary_compression_falls_back_on_error(
        self, ctx: RunContext
    ) -> None:
        settings = Settings(CONTEXT_TRUNCATION_THRESHOLD=100)
        adapter = _make_adapter(_VALID_PLAN_JSON)
        transformer = _make_transformer(_VALID_PLAN_JSON)
        # Make first call (compression) fail; second (decompose) succeed
        adapter.call = AsyncMock(
            side_effect=[RuntimeError("LLM error"), {"raw": "data"}]
        )
        transformer.parse_response = MagicMock(
            return_value=ProviderResult(
                subtask_id="",
                provider_id=ProviderID.ANTHROPIC,
                content=_VALID_PLAN_JSON,
            )
        )
        decomposer = TaskDecomposer(adapter, transformer, settings)

        history = [_user_msg("a" * 30), _user_msg("b" * 30), _user_msg("c" * 30)]
        user_msg = _user_msg("d" * 30)

        # Should not raise — falls back to sliding window
        plan = await decomposer.decompose(user_msg, history, ctx)
        assert plan.summary == "Do something"

    def test_sliding_window_always_keeps_last_message(
        self, settings: Settings
    ) -> None:
        adapter = _make_adapter(_VALID_PLAN_JSON)
        transformer = _make_transformer(_VALID_PLAN_JSON)
        settings = Settings(CONTEXT_TRUNCATION_THRESHOLD=10)  # tiny threshold
        decomposer = TaskDecomposer(adapter, transformer, settings)

        messages = [_user_msg("x" * 50)]  # single large message
        result = decomposer._apply_sliding_window(messages)
        assert len(result) == 1
        assert result[0] is messages[0]

    def test_sliding_window_removes_old_messages(
        self, settings: Settings
    ) -> None:
        # threshold=100, 80%=80. 3 messages of 40 chars each = 120 > 80
        # Should keep the 2 most recent that fit, always keeping the last
        decomposer_settings = Settings(CONTEXT_TRUNCATION_THRESHOLD=100)
        adapter = _make_adapter(_VALID_PLAN_JSON)
        transformer = _make_transformer(_VALID_PLAN_JSON)
        decomposer = TaskDecomposer(adapter, transformer, decomposer_settings)

        messages = [
            _user_msg("a" * 40),  # oldest — should be dropped
            _user_msg("b" * 40),  # middle
            _user_msg("c" * 40),  # newest — always kept
        ]
        result = decomposer._apply_sliding_window(messages)
        # Should include the newest message
        assert any(
            isinstance(m.content[0], TextPart) and "c" in m.content[0].text
            for m in result
        )


# ---------------------------------------------------------------------------
# _parse_task_plan
# ---------------------------------------------------------------------------


class TestParseTaskPlan:
    def _decomposer(self) -> TaskDecomposer:
        return TaskDecomposer(AsyncMock(), MagicMock())

    def test_valid_json(self) -> None:
        d = self._decomposer()
        plan = d._parse_task_plan(_VALID_PLAN_JSON)
        assert plan.summary == "Do something"
        assert plan.subtasks[0].subtask_id == "st_1"

    def test_strips_markdown_fences(self) -> None:
        d = self._decomposer()
        fenced = f"```json\n{_VALID_PLAN_JSON}\n```"
        plan = d._parse_task_plan(fenced)
        assert plan.summary == "Do something"

    def test_strips_plain_code_fence(self) -> None:
        d = self._decomposer()
        fenced = f"```\n{_VALID_PLAN_JSON}\n```"
        plan = d._parse_task_plan(fenced)
        assert len(plan.subtasks) == 1

    def test_invalid_json_raises_transform_error(self) -> None:
        d = self._decomposer()
        with pytest.raises(TransformError, match="invalid JSON"):
            d._parse_task_plan("not json at all")

    def test_unknown_capability_defaults_to_text(self) -> None:
        d = self._decomposer()
        data = {
            "summary": "test",
            "subtasks": [
                {
                    "subtask_id": "st_1",
                    "description": "do thing",
                    "capability": "unknown_capability_xyz",
                    "depends_on": [],
                }
            ],
        }
        plan = d._parse_task_plan(json.dumps(data))
        assert plan.subtasks[0].capability == Capability.TEXT

    def test_empty_subtasks(self) -> None:
        d = self._decomposer()
        plan = d._parse_task_plan(json.dumps({"summary": "empty", "subtasks": []}))
        assert plan.subtasks == []
        assert plan.summary == "empty"

    def test_subtask_with_auto_generated_id(self) -> None:
        d = self._decomposer()
        data = {
            "summary": "test",
            "subtasks": [
                {
                    # no subtask_id — should auto-generate
                    "description": "do thing",
                    "capability": "text",
                    "depends_on": [],
                }
            ],
        }
        plan = d._parse_task_plan(json.dumps(data))
        assert plan.subtasks[0].subtask_id  # non-empty auto-generated ID

    def test_all_capabilities_parsed(self) -> None:
        d = self._decomposer()
        for cap in ["text", "code", "search", "image_gen", "video_gen", "analysis"]:
            data = {
                "summary": "x",
                "subtasks": [
                    {
                        "subtask_id": "st",
                        "description": "x",
                        "capability": cap,
                        "depends_on": [],
                    }
                ],
            }
            plan = d._parse_task_plan(json.dumps(data))
            assert plan.subtasks[0].capability == Capability(cap)


# ---------------------------------------------------------------------------
# Fallback adapter (D-09)
# ---------------------------------------------------------------------------


class TestFallbackAdapter:
    @pytest.mark.asyncio
    async def test_fallback_used_on_provider_error(
        self, ctx: RunContext, settings: Settings
    ) -> None:
        primary_adapter = AsyncMock()
        primary_adapter.call = AsyncMock(side_effect=ProviderError("primary down"))
        primary_transformer = _make_transformer(_VALID_PLAN_JSON)

        fallback_adapter = _make_adapter(_VALID_PLAN_JSON)
        fallback_transformer = _make_transformer(_VALID_PLAN_JSON)

        decomposer = TaskDecomposer(
            coordinator_adapter=primary_adapter,
            coordinator_transformer=primary_transformer,
            settings=settings,
            fallback_adapter=fallback_adapter,
            fallback_transformer=fallback_transformer,
        )
        plan = await decomposer.decompose(_user_msg("hello"), [], ctx)

        assert plan.summary == "Do something"
        fallback_adapter.call.assert_called_once()

    @pytest.mark.asyncio
    async def test_provider_error_raised_when_no_fallback(
        self, ctx: RunContext, settings: Settings
    ) -> None:
        primary_adapter = AsyncMock()
        primary_adapter.call = AsyncMock(side_effect=ProviderError("primary down"))
        primary_transformer = _make_transformer(_VALID_PLAN_JSON)

        decomposer = TaskDecomposer(
            coordinator_adapter=primary_adapter,
            coordinator_transformer=primary_transformer,
            settings=settings,
        )
        with pytest.raises(ProviderError):
            await decomposer.decompose(_user_msg("hello"), [], ctx)
