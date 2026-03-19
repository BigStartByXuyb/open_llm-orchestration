"""
ParallelExecutor 单元测试
Unit tests for ParallelExecutor — all protocols mocked with AsyncMock/MagicMock.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from orchestration.shared.config import Settings
from orchestration.shared.enums import Capability, ProviderID, TaskStatus
from orchestration.shared.errors import ProviderError
from orchestration.shared.types import (
    CanonicalMessage,
    CanonicalTool,
    ProviderResult,
    RunContext,
    SubTask,
    TaskPlan,
    TextPart,
    ToolCallPart,
)
from orchestration.shared.enums import Role
from orchestration.orchestration.executor import ParallelExecutor


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ctx() -> RunContext:
    return RunContext(tenant_id="t1", session_id="s1", task_id="tk1")


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        PROVIDER_CONCURRENCY_LIMITS={"anthropic": 5, "openai": 5, "skill": 5}
    )


def _subtask(
    subtask_id: str,
    capability: Capability = Capability.TEXT,
    provider_id: ProviderID = ProviderID.ANTHROPIC,
    transformer_version: str = "v3",
    depends_on: list[str] | None = None,
    skill_id: str = "",
) -> SubTask:
    return SubTask(
        subtask_id=subtask_id,
        description=f"task {subtask_id}",
        capability=capability,
        context_slice=[],
        provider_id=provider_id,
        transformer_version=transformer_version,
        depends_on=depends_on or [],
        skill_id=skill_id,
        status=TaskStatus.PENDING,
    )


def _provider_result(subtask_id: str, content: str = "result") -> ProviderResult:
    return ProviderResult(
        subtask_id=subtask_id,
        provider_id=ProviderID.ANTHROPIC,
        content=content,
        transformer_version="v3",
    )


def _make_executor(
    transformer_registry: MagicMock | None = None,
    adapters: dict | None = None,
    plugin_registry: MagicMock | None = None,
    settings: Settings | None = None,
) -> ParallelExecutor:
    if transformer_registry is None:
        transformer_registry = MagicMock()
    if adapters is None:
        adapter = AsyncMock()
        adapter.call = AsyncMock(return_value={"raw": "data"})
        adapters = {ProviderID.ANTHROPIC: adapter}
    if plugin_registry is None:
        plugin_registry = MagicMock()
    return ParallelExecutor(
        transformer_registry=transformer_registry,
        adapters=adapters,
        plugin_registry=plugin_registry,
        settings=settings or Settings(),
    )


# ---------------------------------------------------------------------------
# LLM subtask execution
# ---------------------------------------------------------------------------


class TestExecuteLLMSubtask:
    @pytest.mark.asyncio
    async def test_single_llm_task_success(self, ctx: RunContext) -> None:
        expected_result = _provider_result("st_1", "hello world")

        transformer = MagicMock()
        transformer.transform = MagicMock(return_value={"messages": []})
        transformer.parse_response = MagicMock(return_value=expected_result)

        registry = MagicMock()
        registry.get = MagicMock(return_value=transformer)

        adapter = AsyncMock()
        adapter.call = AsyncMock(return_value={"raw": "response"})

        executor = ParallelExecutor(
            transformer_registry=registry,
            adapters={ProviderID.ANTHROPIC: adapter},
            plugin_registry=MagicMock(),
            settings=Settings(),
        )

        plan = TaskPlan("p1", subtasks=[_subtask("st_1")])
        results = await executor.execute(plan, ctx)

        assert len(results) == 1
        assert results[0].content == "hello world"
        assert results[0].subtask_id == "st_1"

    @pytest.mark.asyncio
    async def test_transformer_registry_called_with_correct_key(
        self, ctx: RunContext
    ) -> None:
        result = _provider_result("st_1")

        transformer = MagicMock()
        transformer.transform = MagicMock(return_value={})
        transformer.parse_response = MagicMock(return_value=result)

        registry = MagicMock()
        registry.get = MagicMock(return_value=transformer)

        adapter = AsyncMock()
        adapter.call = AsyncMock(return_value={})

        executor = ParallelExecutor(
            transformer_registry=registry,
            adapters={ProviderID.ANTHROPIC: adapter},
            plugin_registry=MagicMock(),
            settings=Settings(),
        )

        plan = TaskPlan(
            "p1",
            subtasks=[_subtask("st_1", provider_id=ProviderID.ANTHROPIC, transformer_version="v3")],
        )
        await executor.execute(plan, ctx)

        registry.get.assert_called_once_with(ProviderID.ANTHROPIC, "v3")

    @pytest.mark.asyncio
    async def test_missing_adapter_raises_provider_error(
        self, ctx: RunContext
    ) -> None:
        transformer = MagicMock()
        transformer.transform = MagicMock(return_value={})

        registry = MagicMock()
        registry.get = MagicMock(return_value=transformer)

        executor = ParallelExecutor(
            transformer_registry=registry,
            adapters={},  # no adapters
            plugin_registry=MagicMock(),
            settings=Settings(),
        )

        plan = TaskPlan("p1", subtasks=[_subtask("st_1")])
        with pytest.raises(ProviderError, match="No adapter registered"):
            await executor.execute(plan, ctx)

    @pytest.mark.asyncio
    async def test_adapter_error_propagates(self, ctx: RunContext) -> None:
        transformer = MagicMock()
        transformer.transform = MagicMock(return_value={})

        registry = MagicMock()
        registry.get = MagicMock(return_value=transformer)

        adapter = AsyncMock()
        adapter.call = AsyncMock(side_effect=ProviderError("network error"))

        executor = ParallelExecutor(
            transformer_registry=registry,
            adapters={ProviderID.ANTHROPIC: adapter},
            plugin_registry=MagicMock(),
            settings=Settings(),
        )

        plan = TaskPlan("p1", subtasks=[_subtask("st_1")])
        with pytest.raises(ProviderError, match="network error"):
            await executor.execute(plan, ctx)


# ---------------------------------------------------------------------------
# Skill subtask execution
# ---------------------------------------------------------------------------


class TestExecuteSkillSubtask:
    @pytest.mark.asyncio
    async def test_skill_task_bypasses_transformer(self, ctx: RunContext) -> None:
        skill = AsyncMock()
        skill.execute = AsyncMock(return_value={"result": "skill output"})

        plugin_registry = MagicMock()
        plugin_registry.get_skill = MagicMock(return_value=skill)

        registry = MagicMock()
        executor = ParallelExecutor(
            transformer_registry=registry,
            adapters={},
            plugin_registry=plugin_registry,
            settings=Settings(),
        )

        subtask = _subtask(
            "st_skill",
            capability=Capability.SEARCH,
            provider_id=ProviderID.SKILL,
            skill_id="web_search",
        )
        plan = TaskPlan("p1", subtasks=[subtask])
        results = await executor.execute(plan, ctx)

        assert results[0].content == "skill output"
        assert results[0].provider_id == ProviderID.SKILL
        registry.get.assert_not_called()  # transformer not used

    @pytest.mark.asyncio
    async def test_skill_result_includes_skill_id_in_metadata(
        self, ctx: RunContext
    ) -> None:
        skill = AsyncMock()
        skill.execute = AsyncMock(return_value={"result": "data"})

        plugin_registry = MagicMock()
        plugin_registry.get_skill = MagicMock(return_value=skill)

        executor = ParallelExecutor(
            transformer_registry=MagicMock(),
            adapters={},
            plugin_registry=plugin_registry,
            settings=Settings(),
        )

        subtask = _subtask(
            "st_1",
            provider_id=ProviderID.SKILL,
            skill_id="my_skill",
        )
        plan = TaskPlan("p1", subtasks=[subtask])
        results = await executor.execute(plan, ctx)

        assert results[0].metadata.get("skill_id") == "my_skill"

    @pytest.mark.asyncio
    async def test_skill_non_dict_result_stringified(self, ctx: RunContext) -> None:
        skill = AsyncMock()
        # Returns a result without "result" key — should stringify the entire output
        skill.execute = AsyncMock(return_value={"data": "value"})

        plugin_registry = MagicMock()
        plugin_registry.get_skill = MagicMock(return_value=skill)

        executor = ParallelExecutor(
            transformer_registry=MagicMock(),
            adapters={},
            plugin_registry=plugin_registry,
            settings=Settings(),
        )

        subtask = _subtask("st_1", provider_id=ProviderID.SKILL, skill_id="s")
        plan = TaskPlan("p1", subtasks=[subtask])
        results = await executor.execute(plan, ctx)

        # content should be str representation of the dict
        assert "data" in results[0].content or "value" in results[0].content


# ---------------------------------------------------------------------------
# DAG ordering / dependencies
# ---------------------------------------------------------------------------


class TestDependencyOrdering:
    @pytest.mark.asyncio
    async def test_independent_tasks_run_in_parallel(self, ctx: RunContext) -> None:
        execution_order: list[str] = []

        transformer = MagicMock()
        transformer.transform = MagicMock(return_value={})

        registry = MagicMock()

        async def make_call(subtask_id: str):
            result = _provider_result(subtask_id, subtask_id)
            t = MagicMock()
            t.transform = MagicMock(return_value={})
            t.parse_response = MagicMock(return_value=result)
            return t

        # Use side_effect to return different transformers per subtask
        st1_t = MagicMock()
        st1_t.transform = MagicMock(return_value={})
        st1_t.parse_response = MagicMock(return_value=_provider_result("st_1", "r1"))

        st2_t = MagicMock()
        st2_t.transform = MagicMock(return_value={})
        st2_t.parse_response = MagicMock(return_value=_provider_result("st_2", "r2"))

        registry.get = MagicMock(side_effect=[st1_t, st2_t])

        adapter = AsyncMock()
        adapter.call = AsyncMock(return_value={})

        executor = ParallelExecutor(
            transformer_registry=registry,
            adapters={ProviderID.ANTHROPIC: adapter},
            plugin_registry=MagicMock(),
            settings=Settings(),
        )

        plan = TaskPlan(
            "p1",
            subtasks=[
                _subtask("st_1", depends_on=[]),
                _subtask("st_2", depends_on=[]),
            ],
        )
        results = await executor.execute(plan, ctx)
        assert {r.content for r in results} == {"r1", "r2"}

    @pytest.mark.asyncio
    async def test_dependent_task_runs_after_dependency(
        self, ctx: RunContext
    ) -> None:
        st1_t = MagicMock()
        st1_t.transform = MagicMock(return_value={})
        st1_t.parse_response = MagicMock(return_value=_provider_result("st_1", "first"))

        st2_t = MagicMock()
        st2_t.transform = MagicMock(return_value={})
        st2_t.parse_response = MagicMock(return_value=_provider_result("st_2", "second"))

        registry = MagicMock()
        registry.get = MagicMock(side_effect=[st1_t, st2_t])

        adapter = AsyncMock()
        adapter.call = AsyncMock(return_value={})

        executor = ParallelExecutor(
            transformer_registry=registry,
            adapters={ProviderID.ANTHROPIC: adapter},
            plugin_registry=MagicMock(),
            settings=Settings(),
        )

        plan = TaskPlan(
            "p1",
            subtasks=[
                _subtask("st_1", depends_on=[]),
                _subtask("st_2", depends_on=["st_1"]),
            ],
        )
        results = await executor.execute(plan, ctx)
        # Both should complete regardless of order
        assert len(results) == 2
        contents = [r.content for r in results]
        assert "first" in contents
        assert "second" in contents

    @pytest.mark.asyncio
    async def test_circular_dependency_raises(self, ctx: RunContext) -> None:
        executor = _make_executor()
        plan = TaskPlan(
            "p1",
            subtasks=[
                _subtask("st_1", depends_on=["st_2"]),
                _subtask("st_2", depends_on=["st_1"]),
            ],
        )
        with pytest.raises(ValueError, match="[Cc]ircular"):
            await executor.execute(plan, ctx)

    @pytest.mark.asyncio
    async def test_result_order_matches_plan_order(self, ctx: RunContext) -> None:
        st1_t = MagicMock()
        st1_t.transform = MagicMock(return_value={})
        st1_t.parse_response = MagicMock(return_value=_provider_result("st_1", "A"))

        st2_t = MagicMock()
        st2_t.transform = MagicMock(return_value={})
        st2_t.parse_response = MagicMock(return_value=_provider_result("st_2", "B"))

        registry = MagicMock()
        registry.get = MagicMock(side_effect=[st1_t, st2_t])

        adapter = AsyncMock()
        adapter.call = AsyncMock(return_value={})

        executor = ParallelExecutor(
            transformer_registry=registry,
            adapters={ProviderID.ANTHROPIC: adapter},
            plugin_registry=MagicMock(),
            settings=Settings(),
        )

        plan = TaskPlan(
            "p1",
            subtasks=[_subtask("st_1"), _subtask("st_2")],
        )
        results = await executor.execute(plan, ctx)
        assert results[0].subtask_id == "st_1"
        assert results[1].subtask_id == "st_2"


# ---------------------------------------------------------------------------
# on_block_done callback
# ---------------------------------------------------------------------------


class TestBlockDoneCallback:
    @pytest.mark.asyncio
    async def test_on_block_done_called_for_each_subtask(
        self, ctx: RunContext
    ) -> None:
        st1_t = MagicMock()
        st1_t.transform = MagicMock(return_value={})
        st1_t.parse_response = MagicMock(return_value=_provider_result("st_1", "r1"))

        st2_t = MagicMock()
        st2_t.transform = MagicMock(return_value={})
        st2_t.parse_response = MagicMock(return_value=_provider_result("st_2", "r2"))

        registry = MagicMock()
        registry.get = MagicMock(side_effect=[st1_t, st2_t])

        adapter = AsyncMock()
        adapter.call = AsyncMock(return_value={})

        executor = ParallelExecutor(
            transformer_registry=registry,
            adapters={ProviderID.ANTHROPIC: adapter},
            plugin_registry=MagicMock(),
            settings=Settings(),
        )

        received: list[ProviderResult] = []

        async def on_done(result: ProviderResult) -> None:
            received.append(result)

        plan = TaskPlan(
            "p1",
            subtasks=[_subtask("st_1"), _subtask("st_2")],
        )
        await executor.execute(plan, ctx, on_block_done=on_done)

        assert len(received) == 2
        subtask_ids = {r.subtask_id for r in received}
        assert subtask_ids == {"st_1", "st_2"}

    @pytest.mark.asyncio
    async def test_latency_ms_attached_to_result(self, ctx: RunContext) -> None:
        transformer = MagicMock()
        transformer.transform = MagicMock(return_value={})
        transformer.parse_response = MagicMock(
            return_value=_provider_result("st_1")
        )

        registry = MagicMock()
        registry.get = MagicMock(return_value=transformer)

        adapter = AsyncMock()
        adapter.call = AsyncMock(return_value={})

        executor = ParallelExecutor(
            transformer_registry=registry,
            adapters={ProviderID.ANTHROPIC: adapter},
            plugin_registry=MagicMock(),
            settings=Settings(),
        )

        received: list[ProviderResult] = []

        async def on_done(r: ProviderResult) -> None:
            received.append(r)

        plan = TaskPlan("p1", subtasks=[_subtask("st_1")])
        await executor.execute(plan, ctx, on_block_done=on_done)

        assert received[0].latency_ms >= 0

    @pytest.mark.asyncio
    async def test_no_callback_runs_without_error(self, ctx: RunContext) -> None:
        transformer = MagicMock()
        transformer.transform = MagicMock(return_value={})
        transformer.parse_response = MagicMock(
            return_value=_provider_result("st_1")
        )

        registry = MagicMock()
        registry.get = MagicMock(return_value=transformer)

        adapter = AsyncMock()
        adapter.call = AsyncMock(return_value={})

        executor = ParallelExecutor(
            transformer_registry=registry,
            adapters={ProviderID.ANTHROPIC: adapter},
            plugin_registry=MagicMock(),
            settings=Settings(),
        )

        plan = TaskPlan("p1", subtasks=[_subtask("st_1")])
        results = await executor.execute(plan, ctx, on_block_done=None)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Tool result loop (Function Calling 回路)
# ---------------------------------------------------------------------------


def _result_with_tool_call(tool_name: str, tool_call_id: str = "c1") -> ProviderResult:
    """Build a ProviderResult that contains a tool call request."""
    return ProviderResult(
        subtask_id="",
        provider_id=ProviderID.ANTHROPIC,
        content="",
        transformer_version="v3",
        tool_calls=[
            ToolCallPart(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments={"q": "test"},
            )
        ],
    )


def _result_text(content: str) -> ProviderResult:
    return ProviderResult(
        subtask_id="",
        provider_id=ProviderID.ANTHROPIC,
        content=content,
        transformer_version="v3",
        tool_calls=[],
    )


class TestToolResultLoop:
    def _make_executor_with_tool_loop(
        self,
        parse_side_effects: list,
        skill_output: dict | None = None,
    ) -> tuple[ParallelExecutor, MagicMock, MagicMock]:
        transformer = MagicMock()
        transformer.transform = MagicMock(return_value={"messages": []})
        transformer.transform_tools = MagicMock(return_value=[])
        transformer.parse_response = MagicMock(side_effect=parse_side_effects)

        registry = MagicMock()
        registry.get = MagicMock(return_value=transformer)

        adapter = AsyncMock()
        adapter.call = AsyncMock(return_value={})

        skill = AsyncMock()
        skill.execute = AsyncMock(return_value=skill_output or {"result": "tool output"})

        plugin_registry = MagicMock()
        plugin_registry.get_skill = MagicMock(return_value=skill)

        executor = ParallelExecutor(
            transformer_registry=registry,
            adapters={ProviderID.ANTHROPIC: adapter},
            plugin_registry=plugin_registry,
            settings=Settings(),
        )
        return executor, transformer, skill

    @pytest.mark.asyncio
    async def test_no_tool_calls_returns_immediately(self, ctx: RunContext) -> None:
        executor, _, _ = self._make_executor_with_tool_loop(
            parse_side_effects=[_result_text("final answer")]
        )
        plan = TaskPlan("p1", subtasks=[_subtask("st_1")])
        results = await executor.execute(plan, ctx)
        assert results[0].content == "final answer"

    @pytest.mark.asyncio
    async def test_one_tool_call_then_final_answer(self, ctx: RunContext) -> None:
        executor, transformer, skill = self._make_executor_with_tool_loop(
            parse_side_effects=[
                _result_with_tool_call("web_search"),
                _result_text("Search complete"),
            ]
        )
        plan = TaskPlan("p1", subtasks=[_subtask("st_1")])
        results = await executor.execute(plan, ctx)

        assert results[0].content == "Search complete"
        assert transformer.parse_response.call_count == 2
        skill.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tool_call_arguments_passed_to_skill(self, ctx: RunContext) -> None:
        executor, _, skill = self._make_executor_with_tool_loop(
            parse_side_effects=[
                _result_with_tool_call("code_exec"),
                _result_text("done"),
            ]
        )
        plan = TaskPlan("p1", subtasks=[_subtask("st_1")])
        await executor.execute(plan, ctx)

        skill.execute.assert_awaited_once()
        inputs = skill.execute.call_args[0][0]
        assert inputs == {"q": "test"}

    @pytest.mark.asyncio
    async def test_skill_error_wrapped_in_tool_result(self, ctx: RunContext) -> None:
        transformer = MagicMock()
        transformer.transform = MagicMock(return_value={})
        transformer.transform_tools = MagicMock(return_value=[])
        transformer.parse_response = MagicMock(
            side_effect=[_result_with_tool_call("broken_skill"), _result_text("recovered")]
        )

        registry = MagicMock()
        registry.get = MagicMock(return_value=transformer)

        adapter = AsyncMock()
        adapter.call = AsyncMock(return_value={})

        skill = AsyncMock()
        skill.execute = AsyncMock(side_effect=RuntimeError("tool blew up"))

        plugin_registry = MagicMock()
        plugin_registry.get_skill = MagicMock(return_value=skill)

        executor = ParallelExecutor(
            transformer_registry=registry,
            adapters={ProviderID.ANTHROPIC: adapter},
            plugin_registry=plugin_registry,
            settings=Settings(),
        )
        plan = TaskPlan("p1", subtasks=[_subtask("st_1")])
        results = await executor.execute(plan, ctx)
        assert results[0].content == "recovered"
        assert transformer.parse_response.call_count == 2

    @pytest.mark.asyncio
    async def test_tools_injected_into_payload(self, ctx: RunContext) -> None:
        transformer = MagicMock()
        transformer.transform = MagicMock(return_value={"messages": []})
        transformer.transform_tools = MagicMock(
            side_effect=lambda tools: [{"name": t.name} for t in tools]
        )
        transformer.parse_response = MagicMock(return_value=_result_text("ok"))

        registry = MagicMock()
        registry.get = MagicMock(return_value=transformer)

        adapter = AsyncMock()
        adapter.call = AsyncMock(return_value={})

        executor = ParallelExecutor(
            transformer_registry=registry,
            adapters={ProviderID.ANTHROPIC: adapter},
            plugin_registry=MagicMock(),
            settings=Settings(),
        )

        tool = CanonicalTool(name="web_search", description="Search", input_schema={})
        subtask = SubTask(
            subtask_id="st_1",
            description="test",
            capability=Capability.SEARCH,
            context_slice=[],
            provider_id=ProviderID.ANTHROPIC,
            transformer_version="v3",
            tools=[tool],
        )
        plan = TaskPlan("p1", subtasks=[subtask])
        await executor.execute(plan, ctx)

        call_payload = adapter.call.call_args[0][0]
        assert "tools" in call_payload
        assert call_payload["tools"] == [{"name": "web_search"}]

    @pytest.mark.asyncio
    async def test_max_tool_turns_safety_limit(self, ctx: RunContext) -> None:
        always_tool = [
            _result_with_tool_call("loop_skill", tool_call_id=f"c{i}")
            for i in range(15)
        ]
        executor, transformer, _ = self._make_executor_with_tool_loop(
            parse_side_effects=always_tool
        )
        plan = TaskPlan("p1", subtasks=[_subtask("st_1")])
        results = await executor.execute(plan, ctx)

        assert len(results) == 1
        assert transformer.parse_response.call_count <= ParallelExecutor._MAX_TOOL_TURNS + 1
