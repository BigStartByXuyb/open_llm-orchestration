"""
OrchestrationEngine 单元测试
Unit tests for OrchestrationEngine — all four sub-components are mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from orchestration.shared.enums import Capability, ProviderID, Role, TaskStatus
from orchestration.shared.types import (
    CanonicalMessage,
    ProviderResult,
    RunContext,
    SubTask,
    TaskPlan,
    TextPart,
)
from orchestration.orchestration.engine import (
    BlockDoneEvent,
    OrchestrationEngine,
    SummaryEvent,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def ctx() -> RunContext:
    return RunContext(tenant_id="t1", session_id="s1", task_id="tk1")


def _user_msg(text: str = "hello") -> CanonicalMessage:
    return CanonicalMessage(role=Role.USER, content=[TextPart(text=text)])


def _subtask(subtask_id: str) -> SubTask:
    return SubTask(
        subtask_id=subtask_id,
        description="test",
        capability=Capability.TEXT,
        context_slice=[],
        provider_id=ProviderID.ANTHROPIC,
        transformer_version="v3",
        depends_on=[],
        status=TaskStatus.PENDING,
    )


def _result(subtask_id: str) -> ProviderResult:
    return ProviderResult(
        subtask_id=subtask_id,
        provider_id=ProviderID.ANTHROPIC,
        content="result content",
        transformer_version="v3",
    )


def _plan(subtask_ids: list[str]) -> TaskPlan:
    return TaskPlan(
        plan_id="p1",
        subtasks=[_subtask(sid) for sid in subtask_ids],
        summary="test plan",
    )


def _make_engine(
    plan: TaskPlan | None = None,
    results: list[ProviderResult] | None = None,
    summary: str = "final summary",
) -> tuple[OrchestrationEngine, MagicMock, MagicMock, MagicMock, MagicMock]:
    """Build engine with fully mocked components. Returns (engine, decomposer, router, executor, aggregator)."""
    if plan is None:
        plan = _plan(["st_1"])
    if results is None:
        results = [_result("st_1")]

    decomposer = AsyncMock()
    decomposer.decompose = AsyncMock(return_value=plan)

    router = MagicMock()
    router.route_plan = MagicMock(return_value=plan)

    executor = AsyncMock()
    executor.execute = AsyncMock(return_value=results)

    aggregator = AsyncMock()
    aggregator.aggregate = AsyncMock(return_value=summary)

    engine = OrchestrationEngine(
        decomposer=decomposer,
        router=router,
        executor=executor,
        aggregator=aggregator,
    )
    return engine, decomposer, router, executor, aggregator


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


class TestEnginePipeline:
    @pytest.mark.asyncio
    async def test_run_returns_final_summary(self, ctx: RunContext) -> None:
        engine, *_ = _make_engine(summary="the answer")
        result = await engine.run(_user_msg("question"), [], ctx)
        assert result == "the answer"

    @pytest.mark.asyncio
    async def test_decompose_called_with_user_message(self, ctx: RunContext) -> None:
        engine, decomposer, *_ = _make_engine()
        msg = _user_msg("test question")
        history = [_user_msg("old")]
        await engine.run(msg, history, ctx)

        decomposer.decompose.assert_called_once_with(msg, history, ctx, doc_retriever=None)

    @pytest.mark.asyncio
    async def test_router_called_with_decomposer_plan(self, ctx: RunContext) -> None:
        plan = _plan(["st_1", "st_2"])
        engine, _, router, *_ = _make_engine(plan=plan)
        await engine.run(_user_msg(), [], ctx)

        router.route_plan.assert_called_once_with(plan)

    @pytest.mark.asyncio
    async def test_executor_called_with_routed_plan(self, ctx: RunContext) -> None:
        plan = _plan(["st_1"])
        engine, _, router, executor, _ = _make_engine(plan=plan)

        routed_plan = _plan(["st_1_routed"])
        router.route_plan = MagicMock(return_value=routed_plan)

        await engine.run(_user_msg(), [], ctx)
        # executor.execute's first arg should be the routed plan
        call_args = executor.execute.call_args
        assert call_args[0][0] is routed_plan

    @pytest.mark.asyncio
    async def test_aggregator_called_with_results(self, ctx: RunContext) -> None:
        results = [_result("st_1"), _result("st_2")]
        engine, _, _, executor, aggregator = _make_engine(results=results)
        executor.execute = AsyncMock(return_value=results)

        msg = _user_msg("hello")
        await engine.run(msg, [], ctx)

        agg_call = aggregator.aggregate.call_args
        assert agg_call.kwargs.get("results") == results or agg_call[1].get("results") == results or results in agg_call[0]

    @pytest.mark.asyncio
    async def test_run_without_event_sink(self, ctx: RunContext) -> None:
        engine, *_ = _make_engine()
        # Should not raise — event_sink defaults to None
        result = await engine.run(_user_msg(), [], ctx, event_sink=None)
        assert result == "final summary"


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


class TestEventEmission:
    @pytest.mark.asyncio
    async def test_block_done_events_emitted(self, ctx: RunContext) -> None:
        engine, _, _, executor, _ = _make_engine(results=[_result("st_1")])

        events: list = []

        async def sink(event) -> None:
            events.append(event)

        # Capture the on_block_done callback passed to executor
        captured_callback = None

        async def mock_execute(plan, context, on_block_done=None, **kwargs):
            nonlocal captured_callback
            captured_callback = on_block_done
            # Simulate triggering the callback
            if on_block_done:
                await on_block_done(_result("st_1"))
            return [_result("st_1")]

        executor.execute = mock_execute

        await engine.run(_user_msg(), [], ctx, event_sink=sink)

        block_events = [e for e in events if isinstance(e, BlockDoneEvent)]
        assert len(block_events) >= 1
        assert block_events[0].block_id == "st_1"

    @pytest.mark.asyncio
    async def test_summary_start_event_emitted(self, ctx: RunContext) -> None:
        engine, *_ = _make_engine()
        events: list = []

        async def sink(event) -> None:
            events.append(event)

        await engine.run(_user_msg(), [], ctx, event_sink=sink)

        summary_starts = [
            e for e in events if isinstance(e, SummaryEvent) and e.event_type == "start"
        ]
        assert len(summary_starts) == 1

    @pytest.mark.asyncio
    async def test_summary_done_event_emitted(self, ctx: RunContext) -> None:
        engine, *_ = _make_engine(summary="done text")
        events: list = []

        async def sink(event) -> None:
            events.append(event)

        await engine.run(_user_msg(), [], ctx, event_sink=sink)

        summary_dones = [
            e for e in events if isinstance(e, SummaryEvent) and e.event_type == "done"
        ]
        assert len(summary_dones) == 1
        assert summary_dones[0].full_text == "done text"

    @pytest.mark.asyncio
    async def test_summary_delta_events_emitted_via_aggregator_callback(
        self, ctx: RunContext
    ) -> None:
        engine, _, _, _, aggregator = _make_engine()
        events: list = []

        async def sink(event) -> None:
            events.append(event)

        # Capture on_summary_chunk and invoke it
        async def mock_aggregate(**kwargs):
            on_chunk = kwargs.get("on_summary_chunk")
            if on_chunk:
                await on_chunk("delta1")
                await on_chunk("delta2")
            return "full text"

        aggregator.aggregate = mock_aggregate

        await engine.run(_user_msg(), [], ctx, event_sink=sink)

        delta_events = [
            e for e in events if isinstance(e, SummaryEvent) and e.event_type == "delta"
        ]
        assert len(delta_events) == 2
        assert delta_events[0].delta == "delta1"
        assert delta_events[1].delta == "delta2"

    @pytest.mark.asyncio
    async def test_no_events_without_event_sink(self, ctx: RunContext) -> None:
        engine, _, _, executor, aggregator = _make_engine()

        # Neither executor nor aggregator should receive a callback that emits
        called_with_sink = []

        async def mock_execute(plan, context, on_block_done=None, **kwargs):
            called_with_sink.append(on_block_done)
            return [_result("st_1")]

        executor.execute = mock_execute
        await engine.run(_user_msg(), [], ctx, event_sink=None)

        # Callback exists but calling it with no sink should be a no-op
        cb = called_with_sink[0]
        if cb:
            await cb(_result("st_1"))  # must not raise


# ---------------------------------------------------------------------------
# BlockDoneEvent and SummaryEvent dataclass tests
# ---------------------------------------------------------------------------


class TestEventDataclasses:
    def test_block_done_event_fields(self) -> None:
        event = BlockDoneEvent(
            block_id="b1",
            provider_id="anthropic",
            content="text",
            latency_ms=100.0,
            tokens_used=50,
            transformer_version="v3",
        )
        assert event.block_id == "b1"
        assert event.latency_ms == 100.0
        assert event.metadata == {}

    def test_summary_event_defaults(self) -> None:
        event = SummaryEvent(event_type="start")
        assert event.delta == ""
        assert event.full_text == ""

    def test_summary_done_event(self) -> None:
        event = SummaryEvent(event_type="done", full_text="complete summary")
        assert event.full_text == "complete summary"
