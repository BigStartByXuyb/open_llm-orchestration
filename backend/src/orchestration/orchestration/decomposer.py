"""
任务分解器 — 调协调者 LLM 将用户请求分解为 SubTask 列表
Task decomposer — calls coordinator LLM to break user request into SubTasks.

Layer 2: Only imports from shared/. Knows only Protocols, not concrete classes.
第 2 层：仅从 shared/ 导入，只知道 Protocol，不知道具体类。
"""

from __future__ import annotations

import json
import uuid

import logging

from orchestration.shared.config import Settings, get_settings
from orchestration.shared.enums import Capability, ProviderID, Role, TaskStatus
from orchestration.shared.errors import ProviderError, TransformError
from orchestration.shared.protocols import (
    DocumentRetrieverProtocol,
    InstructionTransformer,
    ProviderAdapter,
)

logger = logging.getLogger(__name__)
from orchestration.shared.types import (
    CanonicalMessage,
    RunContext,
    SubTask,
    TaskPlan,
    TextPart,
)

_RAG_CONTEXT_HEADER = """\
Relevant knowledge base documents (use as additional context if applicable):
以下是知识库中与用户请求相关的文档（如适用，可作为额外背景参考）：
"""


def _extract_query_text(message: CanonicalMessage) -> str:
    """从 CanonicalMessage 提取纯文本用于 RAG 查询 / Extract plain text for RAG query."""
    parts = [p.text for p in message.content if isinstance(p, TextPart)]
    return " ".join(parts)[:500]  # cap at 500 chars for query efficiency


def _format_rag_context(docs: list[tuple[str, str]]) -> str:
    """将 (doc_id, content) 列表格式化为系统 prompt 附件 / Format docs as system prompt appendix."""
    lines = [_RAG_CONTEXT_HEADER]
    for doc_id, content in docs:
        preview = content[:800]  # cap per-doc to avoid ballooning system prompt
        lines.append(f"[doc:{doc_id}] {preview}")
    return "\n".join(lines)


_DECOMPOSE_SYSTEM_PROMPT = """\
You are a task decomposition assistant. Given a user request and conversation history,
analyze the request and break it into the minimum necessary subtasks.

Return ONLY a JSON object (no markdown fences, no explanation) with this structure:
{
  "summary": "<brief plan description>",
  "subtasks": [
    {
      "subtask_id": "<unique id like st_1>",
      "description": "<what this subtask does>",
      "capability": "<one of: text, code, search, image_gen, video_gen, analysis>",
      "depends_on": []
    }
  ]
}

Decomposition rules:
- If the request can be answered with a SINGLE call (question, writing, simple code) → return EXACTLY 1 subtask.
- Only decompose when genuinely requiring DIFFERENT systems (e.g., web search AND image generation).
- Typical plan: 1-3 subtasks. Hard limit: 5. Never decompose for its own sake.

Capability routing — what each maps to:
- "text"      → Anthropic Claude (same as coordinator). Use for: Q&A, writing, summarization, simple code
- "code"      → Anthropic Claude (same model). Use for: programming tasks, debugging, code review
- "analysis"  → OpenAI GPT. Use for: structured data analysis, math, numeric reasoning
- "search"    → web search plugin. Use for: current events, real-time factual lookup
- "image_gen" → image model (Jimeng). ONLY for: creating/generating images
- "video_gen" → video model (Kling). ONLY for: creating/generating video clips
Key: "text" and "code" route to the SAME model. Prefer "text" unless the task is clearly programming.

Examples:
User: "What is the capital of France?"
{"summary": "Answer a geography question.", "subtasks": [{"subtask_id": "st_1", "description": "Answer: what is the capital of France?", "capability": "text", "depends_on": []}]}

User: "Search for the latest AI news and write a summary report."
{"summary": "Search for AI news, then summarize the results.", "subtasks": [{"subtask_id": "st_1", "description": "Search the web for the latest AI news.", "capability": "search", "depends_on": []}, {"subtask_id": "st_2", "description": "Write a summary report based on the search results.", "capability": "text", "depends_on": ["st_1"]}]}

User: "Write a Python script to parse CSV files and generate a banner image for it."
{"summary": "Write a CSV parser script and generate a promotional banner image.", "subtasks": [{"subtask_id": "st_1", "description": "Write a Python script that parses CSV files.", "capability": "code", "depends_on": []}, {"subtask_id": "st_2", "description": "Generate a banner image for the CSV parser tool.", "capability": "image_gen", "depends_on": []}]}\
"""


class TaskDecomposer:
    """
    任务分解器 — 调协调者 LLM 将用户请求分解为 SubTask 列表
    Task decomposer — calls coordinator LLM to break user request into SubTasks.

    Applies context truncation before calling the LLM:
      > 80% threshold → sliding window
      > 95% threshold → summary compression (calls LLM to summarize old turns)
    在调用 LLM 前应用上下文截断：
      > 80% 阈值 → 滑动窗口
      > 95% 阈值 → 摘要压缩（调 LLM 摘要旧轮次）
    """

    def __init__(
        self,
        coordinator_adapter: ProviderAdapter,
        coordinator_transformer: InstructionTransformer,
        settings: Settings | None = None,
        fallback_adapter: ProviderAdapter | None = None,
        fallback_transformer: InstructionTransformer | None = None,
    ) -> None:
        self._adapter = coordinator_adapter
        self._transformer = coordinator_transformer
        self._settings = settings or get_settings()
        self._fallback_adapter = fallback_adapter
        self._fallback_transformer = fallback_transformer

    async def decompose(
        self,
        user_message: CanonicalMessage,
        history: list[CanonicalMessage],
        context: RunContext,
        doc_retriever: DocumentRetrieverProtocol | None = None,
        override_adapters: dict[ProviderID, ProviderAdapter] | None = None,
    ) -> TaskPlan:
        """
        将用户消息分解为任务计划 / Decompose user message into a task plan.

        Applies context truncation before calling the coordinator LLM.
        在调用协调者 LLM 之前应用上下文截断。

        doc_retriever: 可选的 RAG 文档检索器，注入时会在 system prompt 中附加相关知识库文档。
                       Optional RAG document retriever; when provided, relevant docs are appended
                       to the system prompt for context enrichment.
        """
        # Build full message list for truncation check
        all_messages = list(history) + [user_message]
        total_chars = sum(m.char_count() for m in all_messages)

        # Apply truncation if needed
        if total_chars > self._settings.summary_compression_threshold:
            all_messages = await self._apply_summary_compression(all_messages, context)
        elif total_chars > self._settings.sliding_window_threshold:
            all_messages = self._apply_sliding_window(all_messages)

        # RAG enrichment: inject relevant knowledge-base docs into system prompt
        # RAG 增强：将相关知识库文档注入 system prompt
        rag_extra = ""
        if doc_retriever and self._settings.RAG_TOP_K > 0:
            query_text = _extract_query_text(user_message)
            if query_text.strip():
                try:
                    docs = await doc_retriever.retrieve_relevant(
                        tenant_id=context.tenant_id,
                        query=query_text,
                        top_k=self._settings.RAG_TOP_K,
                    )
                    if docs:
                        rag_extra = _format_rag_context(docs)
                except Exception:
                    # Non-fatal: continue without RAG if retrieval fails
                    # 非致命：检索失败时继续（不带 RAG 上下文）
                    pass

        # Add decomposition system prompt (with optional RAG context)
        system_text = self._settings.COORDINATOR_DECOMPOSE_PROMPT or _DECOMPOSE_SYSTEM_PROMPT
        if rag_extra:
            system_text = f"{_DECOMPOSE_SYSTEM_PROMPT}\n\n{rag_extra}"

        system_msg = CanonicalMessage(
            role=Role.SYSTEM,
            content=[TextPart(text=system_text)],
        )
        messages_for_llm = [system_msg] + all_messages

        # Resolve effective adapter: prefer tenant override if available for coordinator provider
        # 解析有效 adapter：优先使用租户覆盖（如果存在协调者 provider 的覆盖）
        effective_adapter = (
            (override_adapters or {}).get(self._adapter.provider_id) or self._adapter
        )

        # Call coordinator LLM (with fallback on ProviderError)
        # 调用协调者 LLM（ProviderError 时自动切换备用 adapter）
        try:
            payload = self._transformer.transform(messages_for_llm)
            raw_response = await effective_adapter.call(payload, context)
            result = self._transformer.parse_response(raw_response)
        except ProviderError as primary_exc:
            if self._fallback_adapter is None or self._fallback_transformer is None:
                raise
            logger.warning(
                "Primary coordinator failed (%s), retrying with fallback adapter",
                primary_exc,
            )
            effective_fallback = (
                (override_adapters or {}).get(self._fallback_adapter.provider_id)
                or self._fallback_adapter
            )
            fallback_payload = self._fallback_transformer.transform(messages_for_llm)
            raw_response = await effective_fallback.call(fallback_payload, context)
            result = self._fallback_transformer.parse_response(raw_response)

        return self._parse_task_plan(result.content)

    def _apply_sliding_window(
        self, messages: list[CanonicalMessage]
    ) -> list[CanonicalMessage]:
        """
        滑动窗口截断：保留最新消息直到总字符数低于阈值
        Sliding window: keep most recent messages until total chars below threshold.

        Always preserves at least the last (most recent) message.
        始终保留至少最后（最新）的消息。
        """
        threshold = self._settings.sliding_window_threshold
        result: list[CanonicalMessage] = []
        total = 0
        for msg in reversed(messages):
            msg_chars = msg.char_count()
            # Always add the first message we encounter (the most recent)
            if total + msg_chars > threshold and result:
                break
            result.insert(0, msg)
            total += msg_chars
        return result if result else messages[-1:]

    async def _apply_summary_compression(
        self,
        messages: list[CanonicalMessage],
        context: RunContext,
    ) -> list[CanonicalMessage]:
        """
        摘要压缩：调协调者 LLM 生成历史摘要，压缩为一条 system 消息
        Summary compression: call coordinator LLM to summarize old turns.

        Preserves the last message (current user input), summarizes everything else.
        保留最后一条消息（当前用户输入），摘要其他所有内容。
        Falls back to sliding window if compression fails.
        压缩失败时回退到滑动窗口。
        """
        if len(messages) <= 1:
            return messages

        to_summarize = messages[:-1]
        last_message = messages[-1]

        # Build conversation text for summarization
        conv_text = "\n".join(
            f"[{m.role}]: "
            + " ".join(
                part.text if isinstance(part, TextPart) else ""
                for part in m.content
            )
            for m in to_summarize
        )

        summary_prompt = CanonicalMessage(
            role=Role.USER,
            content=[
                TextPart(
                    text=(
                        "Summarize the following conversation history in 2-3 sentences. "
                        "Focus on key decisions, context, and outcomes. "
                        "Reply with ONLY the summary text, no preamble.\n\n"
                        f"Conversation:\n{conv_text}"
                    )
                )
            ],
        )

        try:
            payload = self._transformer.transform([summary_prompt])
            raw = await self._adapter.call(payload, context)
            summary_result = self._transformer.parse_response(raw)

            summary_message = CanonicalMessage(
                role=Role.SYSTEM,
                content=[
                    TextPart(
                        text=f"[Conversation history summary]: {summary_result.content}"
                    )
                ],
            )
            return [summary_message, last_message]
        except Exception:
            # Fallback to sliding window on any error
            return self._apply_sliding_window(messages)

    def _parse_task_plan(self, content: str) -> TaskPlan:
        """
        从 LLM 响应中解析 TaskPlan JSON / Parse TaskPlan JSON from LLM response.

        Strips markdown code fences if present.
        如果存在 Markdown 代码围栏则去除。
        """
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            )

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise TransformError(
                f"Coordinator returned invalid JSON for task plan: {exc}",
                code="invalid_task_plan_json",
            ) from exc

        subtasks: list[SubTask] = []
        for st_data in data.get("subtasks", []):
            capability_str = st_data.get("capability", "text")
            try:
                capability = Capability(capability_str)
            except ValueError:
                capability = Capability.TEXT

            subtask = SubTask(
                subtask_id=st_data.get("subtask_id", str(uuid.uuid4())),
                description=st_data.get("description", ""),
                capability=capability,
                context_slice=[],
                depends_on=st_data.get("depends_on", []),
                status=TaskStatus.PENDING,
            )
            subtasks.append(subtask)

        plan = TaskPlan(
            plan_id=str(uuid.uuid4()),
            subtasks=subtasks,
            summary=data.get("summary", ""),
        )
        self._validate_plan(plan)
        return plan

    def _validate_plan(self, plan: TaskPlan) -> None:
        """
        验证任务计划的结构完整性 / Validate task plan structural integrity.

        Checks:
          1. At least one subtask (empty plan is a coordinator error).
          2. Subtask count does not exceed MAX_SUBTASKS_PER_PLAN.
          3. All depends_on IDs reference subtasks within the same plan.
        """
        max_subtasks = self._settings.MAX_SUBTASKS_PER_PLAN
        if len(plan.subtasks) > max_subtasks:
            raise TransformError(
                f"Plan has {len(plan.subtasks)} subtasks, exceeding limit of {max_subtasks}",
                code="plan_too_large",
            )

        valid_ids = {st.subtask_id for st in plan.subtasks}
        for st in plan.subtasks:
            unknown = set(st.depends_on) - valid_ids
            if unknown:
                raise TransformError(
                    f"Subtask '{st.subtask_id}' depends_on unknown IDs: {unknown}",
                    code="invalid_depends_on",
                )
