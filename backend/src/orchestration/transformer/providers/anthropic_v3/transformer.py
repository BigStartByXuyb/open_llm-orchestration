"""
AnthropicV3Transformer — Anthropic Messages API v3 格式转换器
AnthropicV3Transformer — Converts canonical messages to Anthropic Messages API format.

Layer 3: Only imports from shared/ and transformer/.
第 3 层：仅从 shared/ 和 transformer/ 导入。

API reference: https://docs.anthropic.com/en/api/messages
Supported features / 支持特性:
  - Text, image (URL + base64), tool use (function calling)
  - System prompt (top-level field, not in messages array)
  - Multi-turn tool use (assistant tool_use + user tool_result)
"""

from __future__ import annotations

import json
from typing import Any

from orchestration.shared.enums import ProviderID
from orchestration.shared.errors import TransformError
from orchestration.shared.types import (
    CanonicalMessage,
    CanonicalTool,
    ImagePart,
    ProviderResult,
    TextPart,
    ToolCallPart,
    ToolResultPart,
)
from orchestration.transformer.base import BaseTransformer


class AnthropicV3Transformer(BaseTransformer):
    """
    Anthropic Messages API v3 格式转换器
    Transformer for Anthropic's Messages API (claude-* models).

    Key Anthropic API conventions / Anthropic API 关键约定:
      - system prompt is a top-level string field, NOT inside messages[]
        system prompt 是顶级字符串字段，不在 messages[] 内
      - images go inside content blocks with type="image"
        图像在 type="image" 的 content block 内
      - tool calls use type="tool_use" in assistant messages
        工具调用在 assistant 消息中使用 type="tool_use"
      - tool results use type="tool_result" in user messages
        工具结果在 user 消息中使用 type="tool_result"
    """

    provider_id: ProviderID = ProviderID.ANTHROPIC
    api_version: str = "v3"

    # Default model — overridden by wiring/container.py via config
    # 默认模型 — 由 wiring/container.py 通过配置覆盖
    DEFAULT_MODEL = "claude-sonnet-4-6"
    DEFAULT_MAX_TOKENS = 8192

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens

    def transform(self, messages: list[CanonicalMessage]) -> dict[str, Any]:
        """
        将 CanonicalMessage 列表转换为 Anthropic Messages API 请求格式
        Convert to Anthropic Messages API request format.

        Anthropic separates system prompt from conversation messages.
        Anthropic 将 system prompt 与对话消息分开。
        """
        system_parts: list[str] = []
        api_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role.value == "system":
                # Collect all system message texts into a single system string
                # 将所有 system 消息文本收集到单个 system 字符串
                for part in msg.content:
                    if isinstance(part, TextPart):
                        system_parts.append(part.text)
            elif msg.role.value in ("user", "assistant", "tool"):
                api_msg = self._convert_message(msg)
                if api_msg is not None:
                    api_messages.append(api_msg)

        if not api_messages:
            raise TransformError(
                "Anthropic API requires at least one non-system message"
            )

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": api_messages,
        }

        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        return payload

    def transform_tools(self, tools: list[CanonicalTool]) -> list[dict[str, Any]]:
        """
        将工具定义转换为 Anthropic tool_use 格式
        Convert tool definitions to Anthropic tool_use format.
        """
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in tools
        ]

    def parse_response(self, raw: dict[str, Any]) -> ProviderResult:
        """
        解析 Anthropic Messages API 响应
        Parse Anthropic Messages API response.

        Response format / 响应格式:
        {
          "id": "msg_xxx",
          "content": [{"type": "text", "text": "..."}, ...],
          "usage": {"input_tokens": N, "output_tokens": M},
          ...
        }
        """
        try:
            content_blocks = raw.get("content", [])
            text_parts: list[str] = []
            tool_call_parts: list[ToolCallPart] = []

            for block in content_blocks:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    # Parse into structured ToolCallPart for executor tool_result 回路
                    # 解析为结构化 ToolCallPart 供 executor tool_result 回路使用
                    tool_call_parts.append(ToolCallPart(
                        tool_call_id=block.get("id", ""),
                        tool_name=block.get("name", ""),
                        arguments=block.get("input", {}),
                    ))

            content = "".join(text_parts)

            usage = raw.get("usage", {})
            tokens_used = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)

            return ProviderResult(
                subtask_id="",  # Filled by executor after this call
                provider_id=self.provider_id,
                content=content,
                transformer_version=self.api_version,
                tokens_used=tokens_used,
                raw_response=raw,
                tool_calls=tool_call_parts,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise TransformError(
                f"Failed to parse Anthropic response: {exc}. Raw: {str(raw)[:200]}"
            ) from exc

    # -----------------------------------------------------------------------
    # Private conversion helpers / 私有转换辅助方法
    # -----------------------------------------------------------------------

    def _convert_message(self, msg: CanonicalMessage) -> dict[str, Any] | None:
        """
        将单条 CanonicalMessage 转换为 Anthropic API message 格式
        Convert a single CanonicalMessage to Anthropic API message format.
        """
        role = "user" if msg.role.value in ("user", "tool") else "assistant"
        content_blocks: list[dict[str, Any]] = []

        for part in msg.content:
            if isinstance(part, TextPart):
                if part.text:  # Skip empty text parts
                    content_blocks.append({"type": "text", "text": part.text})

            elif isinstance(part, ImagePart):
                if part.url:
                    # URL-based image (Anthropic supports URL source)
                    # URL 类型图像
                    content_blocks.append({
                        "type": "image",
                        "source": {
                            "type": "url",
                            "url": part.url,
                        },
                    })
                elif part.data:
                    # Base64-encoded image
                    # Base64 编码图像
                    content_blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": part.media_type,
                            "data": part.data,
                        },
                    })

            elif isinstance(part, ToolCallPart):
                # Tool call in assistant message
                # assistant 消息中的工具调用
                content_blocks.append({
                    "type": "tool_use",
                    "id": part.tool_call_id,
                    "name": part.tool_name,
                    "input": part.arguments,
                })

            elif isinstance(part, ToolResultPart):
                # Tool result in user message
                # user 消息中的工具结果
                content_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": part.tool_call_id,
                    "content": part.content,
                    "is_error": part.is_error,
                })

        if not content_blocks:
            return None

        # Anthropic accepts string content for simple text-only messages
        # 对于纯文本消息，Anthropic 接受字符串格式的 content
        if len(content_blocks) == 1 and content_blocks[0].get("type") == "text":
            return {"role": role, "content": content_blocks[0]["text"]}

        return {"role": role, "content": content_blocks}
