"""
结果聚合器 — 汇总所有 ProviderResult，调协调者 LLM 生成最终汇总
Result aggregator — collects all ProviderResults and calls the coordinator LLM
for a final streaming summary.

Layer 2: Only imports from shared/. Knows only Protocols, not concrete classes.
第 2 层：仅从 shared/ 导入，只知道 Protocol，不知道具体类。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from orchestration.shared.config import Settings, get_settings
from orchestration.shared.protocols import InstructionTransformer, ProviderAdapter
from orchestration.shared.types import (
    CanonicalMessage,
    ProviderResult,
    RunContext,
    TextPart,
)
from orchestration.shared.enums import ProviderID, Role


class ResultAggregator:
    """
    结果聚合器 — 汇总所有 ProviderResult，调协调者 LLM 生成最终流式汇总
    Result aggregator — collects all ProviderResults and calls coordinator LLM
    for a final streaming summary.

    Two-level overflow compression / 两级溢出压缩:
      Level 1: Truncate each block to MAX_RESULT_CHARS_PER_BLOCK
               将每块截断到 MAX_RESULT_CHARS_PER_BLOCK
      Level 2: If total > MAX_SUMMARY_INPUT_CHARS, compress each block to 1 line
               若总量 > MAX_SUMMARY_INPUT_CHARS，将每块压缩为 1 行摘要
    """

    def __init__(
        self,
        coordinator_adapter: ProviderAdapter,
        coordinator_transformer: InstructionTransformer,
        settings: Settings | None = None,
    ) -> None:
        self._adapter = coordinator_adapter
        self._transformer = coordinator_transformer
        self._settings = settings or get_settings()

    async def aggregate(
        self,
        results: list[ProviderResult],
        original_request: CanonicalMessage,
        history: list[CanonicalMessage],
        context: RunContext,
        on_summary_chunk: Callable[[str], Awaitable[None]] | None = None,
        override_adapters: dict[ProviderID, ProviderAdapter] | None = None,
    ) -> str:
        """
        聚合所有子任务结果并生成最终汇总
        Aggregate all subtask results and generate a final summary.

        Streams summary via on_summary_chunk callback if provided.
        如果提供了 on_summary_chunk 回调，则流式推送汇总内容。
        """
        compressed = await self._compress_results(results, context)
        summary_messages = self._build_summary_messages(
            compressed, original_request, history
        )

        # Prefer tenant override adapter for coordinator provider
        # 优先使用租户覆盖的协调者 adapter
        effective_adapter = (
            (override_adapters or {}).get(self._adapter.provider_id) or self._adapter
        )

        payload = self._transformer.transform(summary_messages)
        full_text = ""

        async for chunk in effective_adapter.stream(payload, context):
            full_text += chunk.delta
            if on_summary_chunk and chunk.delta:
                await on_summary_chunk(chunk.delta)

        return full_text

    async def _compress_results(
        self,
        results: list[ProviderResult],
        context: RunContext,
    ) -> list[ProviderResult]:
        """
        两级压缩：单块截断 + 总量上限
        Two-level compression: per-block truncation + total limit.
        """
        max_per_block = self._settings.MAX_RESULT_CHARS_PER_BLOCK
        max_total = self._settings.MAX_SUMMARY_INPUT_CHARS

        # Level 1: truncate each block that exceeds max_per_block
        level1: list[ProviderResult] = []
        for r in results:
            if r.char_count() > max_per_block:
                truncated = r.content[:max_per_block] + " [已截断 / truncated]"
                level1.append(
                    ProviderResult(
                        subtask_id=r.subtask_id,
                        provider_id=r.provider_id,
                        content=truncated,
                        transformer_version=r.transformer_version,
                        tokens_used=r.tokens_used,
                        latency_ms=r.latency_ms,
                        raw_response=r.raw_response,
                        metadata=r.metadata,
                    )
                )
            else:
                level1.append(r)

        # Level 2: compress each block to 1 line if total exceeds max_total
        total_chars = sum(r.char_count() for r in level1)
        if total_chars <= max_total:
            return level1

        level2: list[ProviderResult] = []
        for r in level1:
            summary_prompt = CanonicalMessage(
                role=Role.USER,
                content=[
                    TextPart(
                        text=f"Summarize this result in one sentence:\n{r.content}"
                    )
                ],
            )
            try:
                payload = self._transformer.transform([summary_prompt])
                raw = await self._adapter.call(payload, context)
                summary_result = self._transformer.parse_response(raw)
                level2.append(
                    ProviderResult(
                        subtask_id=r.subtask_id,
                        provider_id=r.provider_id,
                        content=summary_result.content,
                        transformer_version=r.transformer_version,
                        tokens_used=r.tokens_used,
                        latency_ms=r.latency_ms,
                        metadata=r.metadata,
                    )
                )
            except Exception:
                # Fallback: keep first 500 chars
                level2.append(
                    ProviderResult(
                        subtask_id=r.subtask_id,
                        provider_id=r.provider_id,
                        content=r.content[:500],
                        transformer_version=r.transformer_version,
                        tokens_used=r.tokens_used,
                        latency_ms=r.latency_ms,
                        metadata=r.metadata,
                    )
                )

        return level2

    def _build_summary_messages(
        self,
        results: list[ProviderResult],
        original_request: CanonicalMessage,
        history: list[CanonicalMessage],
    ) -> list[CanonicalMessage]:
        """
        构建汇总请求的消息列表 / Build message list for the summary request.
        """
        system_msg = CanonicalMessage(
            role=Role.SYSTEM,
            content=[
                TextPart(
                    text=(
                        "You are a helpful assistant. You have been given the results "
                        "of multiple parallel subtasks. Synthesize them into a coherent, "
                        "comprehensive response to the user's original request."
                    )
                )
            ],
        )

        results_text = "\n\n".join(
            f"## Result from {r.provider_id} (subtask {r.subtask_id}):\n{r.content}"
            for r in results
        )

        original_text = " ".join(
            part.text for part in original_request.content if isinstance(part, TextPart)
        )

        synthesis_prompt = CanonicalMessage(
            role=Role.USER,
            content=[
                TextPart(
                    text=(
                        f"Original request: {original_text}\n\n"
                        f"Subtask results:\n{results_text}\n\n"
                        "Please provide a comprehensive synthesis of these results."
                    )
                )
            ],
        )

        return [system_msg] + list(history) + [synthesis_prompt]
