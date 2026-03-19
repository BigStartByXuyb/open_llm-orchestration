"""
编排引擎 — 协调完整的 LLM 编排管道
Orchestration engine — coordinates the full LLM orchestration pipeline.

Pipeline: decomposer → router → executor → aggregator
管道：decomposer → router → executor → aggregator

Layer 2: Only imports from shared/ and sibling modules.
第 2 层：仅从 shared/ 和同级模块导入。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from orchestration.shared.config import Settings, get_settings
from orchestration.shared.enums import ProviderID
from orchestration.shared.protocols import DocumentRetrieverProtocol, ProviderAdapter
from orchestration.shared.types import CanonicalMessage, ProviderResult, RunContext

from .aggregator import ResultAggregator
from .decomposer import TaskDecomposer
from .executor import ParallelExecutor
from .router import CapabilityRouter


@dataclass
class BlockDoneEvent:
    """
    block_done WebSocket 事件数据 / block_done WebSocket event data.
    Emitted immediately when a subtask completes (real-time visibility).
    子任务完成后立即推送（用户实时可见）。
    """

    block_id: str
    provider_id: str
    content: str
    latency_ms: float
    tokens_used: int
    transformer_version: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SummaryEvent:
    """
    summary 相关 WebSocket 事件数据 / summary WebSocket event data.
    event_type: "start" | "delta" | "done"
    """

    event_type: str
    delta: str = ""
    full_text: str = ""


# EventPayload: either a block completion or a summary lifecycle event
# 事件载荷：子任务完成事件或汇总生命周期事件
EventPayload = BlockDoneEvent | SummaryEvent
EventSink = Callable[[EventPayload], Awaitable[None]]


class OrchestrationEngine:
    """
    编排引擎 — 协调完整的 LLM 编排管道
    Orchestration engine — coordinates the full LLM orchestration pipeline.

    Emits WebSocket events via the optional event_sink:
      - BlockDoneEvent  for each completed subtask
      - SummaryEvent(start/delta/done) during final aggregation
    通过可选的 event_sink 推送 WebSocket 事件：
      - BlockDoneEvent：每个子任务完成时
      - SummaryEvent(start/delta/done)：最终汇总期间
    """

    def __init__(
        self,
        decomposer: TaskDecomposer,
        router: CapabilityRouter,
        executor: ParallelExecutor,
        aggregator: ResultAggregator,
        settings: Settings | None = None,
    ) -> None:
        self._decomposer = decomposer
        self._router = router
        self._executor = executor
        self._aggregator = aggregator
        self._settings = settings or get_settings()

    async def run(
        self,
        user_message: CanonicalMessage,
        history: list[CanonicalMessage],
        context: RunContext,
        event_sink: EventSink | None = None,
        doc_retriever: DocumentRetrieverProtocol | None = None,
        override_adapters: dict[ProviderID, ProviderAdapter] | None = None,
    ) -> str:
        """
        运行完整编排管道，通过 event_sink 推送 WebSocket 事件
        Run the full orchestration pipeline, pushing events via event_sink.

        Returns the final summary text.
        返回最终汇总文本。

        doc_retriever: 可选 RAG 检索器，注入后在分解阶段检索相关文档并注入 system prompt。
                       Optional RAG retriever; when provided, relevant docs are injected into
                       the decomposer's system prompt for context enrichment.
        """
        # Step 1: Decompose user message into SubTasks (with optional RAG enrichment)
        plan = await self._decomposer.decompose(
            user_message, history, context, doc_retriever=doc_retriever
        )

        # Step 2: Route each SubTask to the appropriate provider
        routed_plan = self._router.route_plan(plan)

        # Step 3: Execute all subtasks (parallel where possible)
        async def on_block_done(result: ProviderResult) -> None:
            if event_sink:
                await event_sink(
                    BlockDoneEvent(
                        block_id=result.subtask_id,
                        provider_id=str(result.provider_id),
                        content=result.content,
                        latency_ms=result.latency_ms,
                        tokens_used=result.tokens_used,
                        transformer_version=result.transformer_version,
                        metadata=result.metadata,
                    )
                )

        results = await self._executor.execute(
            routed_plan, context, on_block_done, override_adapters=override_adapters
        )

        # Step 4: Aggregate results into a final summary (streaming)
        if event_sink:
            await event_sink(SummaryEvent(event_type="start"))

        async def on_summary_chunk(delta: str) -> None:
            if event_sink:
                await event_sink(SummaryEvent(event_type="delta", delta=delta))

        summary = await self._aggregator.aggregate(
            results=results,
            original_request=user_message,
            history=history,
            context=context,
            on_summary_chunk=on_summary_chunk,
        )

        if event_sink:
            await event_sink(SummaryEvent(event_type="done", full_text=summary))

        return summary
