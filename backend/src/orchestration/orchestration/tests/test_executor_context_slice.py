"""
N-06: context_slice 序列化修复测试
Tests that _execute_skill() passes context_slice with 'content' field (not 'char_count').
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from orchestration.orchestration.executor import ParallelExecutor
from orchestration.shared.enums import Capability, ProviderID, Role, TaskStatus
from orchestration.shared.types import (
    CanonicalMessage,
    RunContext,
    SubTask,
    TaskPlan,
    TextPart,
)


def _make_context() -> RunContext:
    return RunContext(tenant_id="t1", session_id="s1", task_id="tk1")


def _make_text_message(role: Role, text: str) -> CanonicalMessage:
    return CanonicalMessage(role=role, content=[TextPart(text=text)])


class TestContextSliceSerialization:
    """N-06: _execute_skill() must include 'content' field in context_slice dicts."""

    @pytest.mark.asyncio
    async def test_context_slice_includes_content_field(self) -> None:
        """
        Each context_slice entry passed to skill.execute() must have a non-empty
        'content' field containing the message text (not an integer char_count).
        """
        captured_inputs: list[dict] = []

        async def capture_execute(inputs: dict, ctx: RunContext) -> dict:
            captured_inputs.append(inputs)
            return {"result": "ok"}

        skill = AsyncMock()
        skill.execute = AsyncMock(side_effect=capture_execute)

        plugin_registry = MagicMock()
        plugin_registry.get_skill = MagicMock(return_value=skill)

        executor = ParallelExecutor(
            transformer_registry=MagicMock(),
            adapters={},
            plugin_registry=plugin_registry,
        )

        context_messages = [
            _make_text_message(Role.USER, "Hello, what is Python?"),
            _make_text_message(Role.ASSISTANT, "Python is a programming language."),
        ]

        subtask = SubTask(
            subtask_id="st_ctx",
            description="explain python",
            provider_id=ProviderID.SKILL,
            capability=Capability.TEXT,
            skill_id="test_skill",
            context_slice=context_messages,
            status=TaskStatus.PENDING,
        )
        plan = TaskPlan("p1", subtasks=[subtask])
        ctx = _make_context()

        await executor.execute(plan, ctx)

        assert len(captured_inputs) == 1
        context_slice = captured_inputs[0]["context_slice"]
        assert len(context_slice) == 2

        for i, (item, msg) in enumerate(zip(context_slice, context_messages)):
            # Each item must have a 'content' key
            assert "content" in item, f"context_slice[{i}] missing 'content' key: {item}"
            # Content must be a string (not an integer)
            assert isinstance(item["content"], str), (
                f"context_slice[{i}]['content'] must be str, got {type(item['content'])}: {item}"
            )
            # Content must be non-empty for messages that have text
            assert len(item["content"]) > 0, (
                f"context_slice[{i}]['content'] must be non-empty for text message"
            )
            # Must NOT have char_count (the old buggy field)
            assert "char_count" not in item, (
                f"context_slice[{i}] must not have 'char_count' field (N-06 regression): {item}"
            )

    @pytest.mark.asyncio
    async def test_context_slice_content_matches_message_text(self) -> None:
        """The 'content' field must contain the actual message text."""
        captured_inputs: list[dict] = []

        async def capture_execute(inputs: dict, ctx: RunContext) -> dict:
            captured_inputs.append(inputs)
            return {"result": "ok"}

        skill = AsyncMock()
        skill.execute = AsyncMock(side_effect=capture_execute)

        plugin_registry = MagicMock()
        plugin_registry.get_skill = MagicMock(return_value=skill)

        executor = ParallelExecutor(
            transformer_registry=MagicMock(),
            adapters={},
            plugin_registry=plugin_registry,
        )

        unique_text = "unique-marker-abc123"
        context_messages = [_make_text_message(Role.USER, unique_text)]

        subtask = SubTask(
            subtask_id="st_ctx2",
            description="check content",
            provider_id=ProviderID.SKILL,
            capability=Capability.TEXT,
            skill_id="test_skill",
            context_slice=context_messages,
            status=TaskStatus.PENDING,
        )
        plan = TaskPlan("p1", subtasks=[subtask])
        ctx = _make_context()

        await executor.execute(plan, ctx)

        context_slice = captured_inputs[0]["context_slice"]
        assert unique_text in context_slice[0]["content"], (
            f"Expected '{unique_text}' in content, got: {context_slice[0]['content']}"
        )

    @pytest.mark.asyncio
    async def test_empty_context_slice_produces_empty_list(self) -> None:
        """Empty context_slice must produce an empty list (no crash)."""
        skill = AsyncMock()
        skill.execute = AsyncMock(return_value={"result": "ok"})
        plugin_registry = MagicMock()
        plugin_registry.get_skill = MagicMock(return_value=skill)

        executor = ParallelExecutor(
            transformer_registry=MagicMock(),
            adapters={},
            plugin_registry=plugin_registry,
        )

        subtask = SubTask(
            subtask_id="st_empty",
            description="no context",
            provider_id=ProviderID.SKILL,
            capability=Capability.TEXT,
            skill_id="test_skill",
            context_slice=[],
            status=TaskStatus.PENDING,
        )
        plan = TaskPlan("p1", subtasks=[subtask])
        ctx = _make_context()

        results = await executor.execute(plan, ctx)
        assert len(results) == 1
        # Verify skill was called with empty context_slice
        call_args = skill.execute.call_args[0][0]
        assert call_args["context_slice"] == []
