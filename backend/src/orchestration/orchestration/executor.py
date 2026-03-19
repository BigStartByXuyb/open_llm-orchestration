"""
并行执行器 — 按 DAG 拓扑顺序执行所有 SubTask，含 per-provider 背压控制
Parallel executor — executes SubTasks in DAG topological order with
per-provider back-pressure via asyncio.Semaphore.

Layer 2: Only imports from shared/. Knows only Protocols, not concrete classes.
第 2 层：仅从 shared/ 导入，只知道 Protocol，不知道具体类。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

from orchestration.shared.config import Settings, get_settings
from orchestration.shared.enums import ProviderID, Role
from orchestration.shared.errors import ProviderError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Circuit Breaker  熔断器
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """
    简单的每 provider 熔断器（三态：closed / open / half-open）。
    Simple per-provider circuit breaker (three states: closed / open / half-open).

    - closed：正常运行，跟踪连续失败次数
    - open：快速失败，不执行请求，等待 reset_timeout 后进入 half-open
    - half-open：发送一次探测请求，成功则回到 closed，失败则重回 open
    """

    _STATE_CLOSED = "closed"
    _STATE_OPEN = "open"
    _STATE_HALF_OPEN = "half-open"

    def __init__(self, failure_threshold: int, reset_timeout: float) -> None:
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._failure_count: int = 0
        self._state: str = self._STATE_CLOSED
        self._opened_at: float = 0.0

    @property
    def state(self) -> str:
        """Return current state (closed / open / half-open)."""
        if self._state == self._STATE_OPEN:
            if time.monotonic() - self._opened_at >= self._reset_timeout:
                self._state = self._STATE_HALF_OPEN
        return self._state

    def is_open(self) -> bool:
        """Returns True if requests should be blocked (circuit is open)."""
        return self.state == self._STATE_OPEN

    def record_success(self) -> None:
        """Call after a successful provider call."""
        self._failure_count = 0
        self._state = self._STATE_CLOSED

    def record_failure(self) -> None:
        """Call after a failed provider call."""
        self._failure_count += 1
        if self._failure_count >= self._failure_threshold:
            self._state = self._STATE_OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                "Circuit breaker OPEN after %d consecutive failures",
                self._failure_count,
            )
from orchestration.shared.protocols import (
    PluginRegistryProtocol,
    ProviderAdapter,
    TransformerRegistryProtocol,
)
from orchestration.shared.types import (
    CanonicalMessage,
    ProviderResult,
    RunContext,
    SubTask,
    TaskPlan,
    ToolCallPart,
    ToolResultPart,
)


class ParallelExecutor:
    """
    并行执行器 — 按 DAG 拓扑顺序执行所有 SubTask，含 per-provider 背压控制
    Parallel executor — executes SubTasks in DAG topological order with
    per-provider back-pressure via asyncio.Semaphore.

    LLM subtasks: transformer.transform → adapter.call → transformer.parse_response
    Skill subtasks: plugin_registry.get_skill → skill.execute (bypasses pipeline)
    LLM 子任务：transformer.transform → adapter.call → transformer.parse_response
    Skill 子任务：plugin_registry.get_skill → skill.execute（绕过管道）
    """

    def __init__(
        self,
        transformer_registry: TransformerRegistryProtocol,
        adapters: dict[ProviderID, ProviderAdapter],
        plugin_registry: PluginRegistryProtocol,
        settings: Settings | None = None,
    ) -> None:
        self._transformer_registry = transformer_registry
        self._adapters = adapters
        self._plugin_registry = plugin_registry
        self._settings = settings or get_settings()

        # Build per-provider semaphores for back-pressure
        # 构建每 provider 的 Semaphore 以控制背压
        self._semaphores: dict[str, asyncio.Semaphore] = {
            provider_id: asyncio.Semaphore(limit)
            for provider_id, limit in self._settings.PROVIDER_CONCURRENCY_LIMITS.items()
        }
        self._default_semaphore = asyncio.Semaphore(5)

        # Build per-provider circuit breakers (Sprint 17)
        # 构建每 provider 的熔断器（Sprint 17）
        self._circuit_breakers: dict[str, CircuitBreaker] = {}

    def _get_circuit_breaker(self, provider_id: str) -> CircuitBreaker:
        """Lazily create and return the circuit breaker for a provider."""
        if provider_id not in self._circuit_breakers:
            self._circuit_breakers[provider_id] = CircuitBreaker(
                failure_threshold=self._settings.CIRCUIT_BREAKER_FAILURE_THRESHOLD,
                reset_timeout=self._settings.CIRCUIT_BREAKER_RESET_TIMEOUT,
            )
        return self._circuit_breakers[provider_id]

    async def _call_with_retry(
        self,
        provider_id: str,
        coro_fn: Callable[[], Awaitable[ProviderResult]],
    ) -> ProviderResult:
        """
        带指数退避重试和熔断器的 provider 调用包装器。
        Provider call wrapper with exponential backoff retry and circuit breaker.

        重试策略 / Retry policy:
          - 最多 PROVIDER_MAX_RETRIES 次重试
          - 延迟 = base * 2^attempt + random jitter(0, 0.5)
          - 仅对 ProviderError 重试；其他异常直接传播
          - 重试前检查熔断器状态
        """
        cb = self._get_circuit_breaker(provider_id)
        max_retries = self._settings.PROVIDER_MAX_RETRIES
        base_delay = self._settings.PROVIDER_RETRY_BASE_DELAY
        timeout_secs = self._settings.PROVIDER_TIMEOUT_SECONDS

        last_exc: ProviderError | None = None

        for attempt in range(max_retries + 1):
            if cb.is_open():
                raise ProviderError(
                    f"Circuit breaker OPEN for provider '{provider_id}': "
                    "too many consecutive failures, refusing to call",
                    code="circuit_open",
                    provider_id=provider_id,
                )

            try:
                result = await asyncio.wait_for(coro_fn(), timeout=timeout_secs)
                cb.record_success()
                return result
            except asyncio.TimeoutError:
                cb.record_failure()
                exc = ProviderError(
                    f"Provider '{provider_id}' timed out after {timeout_secs}s",
                    code="timeout",
                    provider_id=provider_id,
                )
                last_exc = exc
                logger.warning(
                    "Provider '%s' timeout on attempt %d/%d",
                    provider_id, attempt + 1, max_retries + 1,
                )
            except ProviderError as exc:
                cb.record_failure()
                last_exc = exc
                logger.warning(
                    "Provider '%s' error on attempt %d/%d: %s",
                    provider_id, attempt + 1, max_retries + 1, exc,
                )

            if attempt < max_retries:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                await asyncio.sleep(delay)

        raise last_exc  # type: ignore[misc]

    async def execute(
        self,
        plan: TaskPlan,
        context: RunContext,
        on_block_done: Callable[[ProviderResult], Awaitable[None]] | None = None,
        override_adapters: dict[ProviderID, ProviderAdapter] | None = None,
    ) -> list[ProviderResult]:
        """
        执行任务计划，并行运行无依赖的子任务
        Execute the task plan, running independent subtasks in parallel.

        Respects depends_on for ordering. Subtasks whose dependencies are all
        complete are executed as a wave via asyncio.gather.
        遵守 depends_on 顺序。所有依赖均完成的子任务作为一波通过 asyncio.gather 并行执行。
        """
        results: dict[str, ProviderResult] = {}
        pending: dict[str, SubTask] = {st.subtask_id: st for st in plan.subtasks}
        completed: set[str] = set()

        while pending:
            # Find all subtasks whose dependencies are satisfied
            ready = [
                st
                for st in pending.values()
                if all(dep in completed for dep in st.depends_on)
            ]

            if not ready:
                raise ValueError(
                    f"Circular dependency or unresolvable dependency in plan "
                    f"{plan.plan_id!r}. Pending: {list(pending)}, "
                    f"Completed: {list(completed)}"
                )

            # Execute the ready wave in parallel
            wave_results = await asyncio.gather(
                *[self._execute_subtask(st, context, on_block_done, override_adapters) for st in ready],
                return_exceptions=True,
            )

            for st, outcome in zip(ready, wave_results):
                if isinstance(outcome, BaseException):
                    raise outcome  # type: ignore[misc]
                results[st.subtask_id] = outcome  # type: ignore[assignment]
                completed.add(st.subtask_id)
                del pending[st.subtask_id]

        # Return in original plan order
        return [results[st.subtask_id] for st in plan.subtasks]

    async def _execute_subtask(
        self,
        subtask: SubTask,
        context: RunContext,
        on_block_done: Callable[[ProviderResult], Awaitable[None]] | None,
        override_adapters: dict[ProviderID, ProviderAdapter] | None = None,
    ) -> ProviderResult:
        """
        执行单个子任务，获取适当的 Semaphore
        Execute a single subtask, acquiring the appropriate Semaphore.
        """
        semaphore = self._semaphores.get(
            str(subtask.provider_id), self._default_semaphore
        )

        async with semaphore:
            start = time.monotonic()

            if subtask.provider_id == ProviderID.SKILL:
                result = await self._execute_skill(subtask, context)
            else:
                # Sprint 17: wrap LLM call with retry + circuit breaker + timeout
                provider_id_str = str(subtask.provider_id)
                result = await self._call_with_retry(
                    provider_id_str,
                    lambda: self._execute_llm(subtask, context, override_adapters),
                )

            latency_ms = (time.monotonic() - start) * 1000

            # N-14: record subtask-level Prometheus metrics
            try:
                from orchestration.gateway.middleware.metrics import (  # noqa: PLC0415
                    subtask_duration_seconds,
                    subtask_total,
                )
                subtask_duration_seconds.labels(
                    capability=subtask.capability.value,
                    provider=str(subtask.provider_id),
                ).observe(latency_ms / 1000)
                subtask_total.labels(
                    capability=subtask.capability.value,
                    status="success",
                ).inc()
            except Exception:  # pragma: no cover — metrics import is optional
                pass

            final_result = ProviderResult(
                subtask_id=result.subtask_id,
                provider_id=result.provider_id,
                content=result.content,
                transformer_version=result.transformer_version,
                tokens_used=result.tokens_used,
                latency_ms=latency_ms,
                raw_response=result.raw_response,
                metadata={
                    **result.metadata,
                    "description": subtask.description,
                    "capability": subtask.capability.value,
                },
            )

        if on_block_done:
            await on_block_done(final_result)

        return final_result

    # Safety cap on tool call turns per subtask
    # 每个子任务工具调用轮次的安全上限
    _MAX_TOOL_TURNS = 10

    async def _execute_llm(
        self,
        subtask: SubTask,
        context: RunContext,
        override_adapters: dict[ProviderID, ProviderAdapter] | None = None,
    ) -> ProviderResult:
        """
        通过 transformer + adapter 管道执行 LLM 子任务，含 tool_result 回路
        Execute LLM subtask via transformer + adapter pipeline with tool_result loop.

        override_adapters: 租户级 adapter 覆盖（优先于全局 adapter）
                           Tenant-level adapter overrides (take precedence over global adapters).

        tool_result 回路 / tool_result loop:
          1. Transform + call adapter
          2. If response contains tool_calls → execute tools via plugin_registry
          3. Append assistant tool_call message + tool result message to context
          4. Repeat until no tool_calls or _MAX_TOOL_TURNS reached
        """
        transformer = self._transformer_registry.get(
            subtask.provider_id, subtask.transformer_version
        )
        # Prefer tenant-level adapter override when available
        # 优先使用租户级 adapter 覆盖
        adapter = (
            (override_adapters or {}).get(subtask.provider_id)
            or self._adapters.get(subtask.provider_id)
        )
        if adapter is None:
            raise ProviderError(
                f"No adapter registered for provider {subtask.provider_id!r}",
                code="missing_adapter",
                provider_id=str(subtask.provider_id),
            )

        # Work on a mutable copy of context_slice so we can append tool messages
        # 使用 context_slice 的可变副本，以便追加工具消息
        context_slice = list(subtask.context_slice)
        result: ProviderResult | None = None

        for tool_turn in range(self._MAX_TOOL_TURNS + 1):
            payload = transformer.transform(context_slice)

            # Inject tool definitions if the subtask declares them
            # 若子任务声明了工具，将工具定义注入 payload
            if subtask.tools:
                tools_payload = transformer.transform_tools(subtask.tools)
                if tools_payload:
                    payload["tools"] = tools_payload

            raw_response = await adapter.call(payload, context)
            result = transformer.parse_response(raw_response)

            if not result.tool_calls:
                # No tool calls — we're done
                # 无工具调用 — 完成
                return result

            if tool_turn >= self._MAX_TOOL_TURNS:
                # Safety limit reached — return the last result as-is
                # 达到安全上限 — 原样返回最后结果
                break

            # Build assistant message containing the tool call requests
            # 构建包含工具调用请求的 assistant 消息
            assistant_msg = CanonicalMessage(
                role=Role.ASSISTANT,
                content=list(result.tool_calls),  # type: ignore[arg-type]
            )
            context_slice.append(assistant_msg)

            # Execute each tool call and collect results
            # 执行每个工具调用并收集结果
            tool_result_parts: list[ToolResultPart] = []
            for tool_call in result.tool_calls:
                if not isinstance(tool_call, ToolCallPart):
                    continue
                try:
                    skill = self._plugin_registry.get_skill(tool_call.tool_name)
                    output = await skill.execute(tool_call.arguments, context)
                    content = (
                        output if isinstance(output, str)
                        else json.dumps(output, ensure_ascii=False)
                    )
                    tool_result_parts.append(ToolResultPart(
                        tool_call_id=tool_call.tool_call_id,
                        content=content,
                        is_error=False,
                    ))
                except Exception as exc:
                    tool_result_parts.append(ToolResultPart(
                        tool_call_id=tool_call.tool_call_id,
                        content=str(exc),
                        is_error=True,
                    ))

            # Append tool results as a single tool-role message
            # 将工具结果作为单条 tool 角色消息追加
            tool_result_msg = CanonicalMessage(
                role=Role.TOOL,
                content=tool_result_parts,  # type: ignore[arg-type]
            )
            context_slice.append(tool_result_msg)

        # result is never None here (loop runs at least once)
        return result  # type: ignore[return-value]

    async def _execute_skill(
        self,
        subtask: SubTask,
        context: RunContext,
    ) -> ProviderResult:
        """
        执行 Skill 子任务（绕过 transformer/adapter 管道）
        Execute Skill subtask (bypasses transformer/adapter pipeline entirely).
        """
        skill = self._plugin_registry.get_skill(subtask.skill_id)

        # N-06 fix: include actual message text (not just char_count) so PromptSkill
        # can render context correctly. char_count was an integer causing fallback
        # to display a number instead of readable text.
        inputs: dict[str, Any] = {
            "description": subtask.description,
            "context_slice": [
                {
                    "role": str(m.role),
                    "content": " ".join(
                        part.text for part in m.content if hasattr(part, "text")
                    ),
                }
                for m in subtask.context_slice
            ],
        }

        output = await skill.execute(inputs, context)

        # Handle prompt_injection result type from PromptSkill
        # 处理 PromptSkill 返回的 prompt_injection 结果类型
        # N-04 verified: output.get("prompt", "") correctly reads prompt field ✅
        # N-13 verified: prompt_injection result_type is correctly handled here ✅
        result_type = output.get("result_type", "result")
        if result_type == "prompt_injection":
            content = str(output.get("prompt", ""))
        else:
            content = str(output.get("result", output))

        return ProviderResult(
            subtask_id=subtask.subtask_id,
            provider_id=ProviderID.SKILL,
            content=content,
            transformer_version="v1",
            metadata={"skill_id": subtask.skill_id, "result_type": result_type},
        )
