"""
OpenAIV1Transformer — OpenAI Chat Completions API v1 格式转换器
OpenAIV1Transformer — Converts canonical messages to OpenAI Chat Completions API format.

Layer 3: Only imports from shared/ and transformer/.
第 3 层：仅从 shared/ 和 transformer/ 导入。

Supported features / 支持特性:
  - Text, image (URL + base64 via data URI), tool calls (function calling)
  - System prompt as first message with role="system"
  - Multi-turn tool use (assistant tool_calls + tool role messages)

Note: DeepSeek uses the same format (OpenAI-compatible), handled by deepseek_v1/.
注意：DeepSeek 使用相同格式（OpenAI 兼容），由 deepseek_v1/ 处理。
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


class OpenAIV1Transformer(BaseTransformer):
    """
    OpenAI Chat Completions API v1 格式转换器
    Transformer for OpenAI's Chat Completions API (gpt-* models).

    Key OpenAI API conventions / OpenAI API 关键约定:
      - system prompt uses role="system" as the first message
        system prompt 使用 role="system" 作为第一条消息
      - images go inside content array with type="image_url"
        图像在 content 数组的 type="image_url" 对象内
      - tool calls in assistant messages use tool_calls[] array
        assistant 消息中的工具调用使用 tool_calls[] 数组
      - tool results use role="tool" with tool_call_id
        工具结果使用 role="tool" 和 tool_call_id
    """

    provider_id: ProviderID = ProviderID.OPENAI
    api_version: str = "v1"

    DEFAULT_MODEL = "gpt-4o"
    DEFAULT_MAX_TOKENS = 4096

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens

    def transform(self, messages: list[CanonicalMessage]) -> dict[str, Any]:
        """
        将 CanonicalMessage 列表转换为 OpenAI Chat Completions API 请求格式
        Convert to OpenAI Chat Completions API request format.
        """
        api_messages: list[dict[str, Any]] = []

        for msg in messages:
            converted = self._convert_message(msg)
            if converted is not None:
                if isinstance(converted, list):
                    api_messages.extend(converted)
                else:
                    api_messages.append(converted)

        if not api_messages:
            raise TransformError("OpenAI API requires at least one message")

        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": api_messages,
        }

    def transform_tools(self, tools: list[CanonicalTool]) -> list[dict[str, Any]]:
        """
        将工具定义转换为 OpenAI function calling 格式
        Convert tool definitions to OpenAI function calling format.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in tools
        ]

    def parse_response(self, raw: dict[str, Any]) -> ProviderResult:
        """
        解析 OpenAI Chat Completions API 响应
        Parse OpenAI Chat Completions API response.

        Response format / 响应格式:
        {
          "choices": [{"message": {"content": "...", "tool_calls": [...]}}],
          "usage": {"prompt_tokens": N, "completion_tokens": M, "total_tokens": T},
          ...
        }
        """
        try:
            choices = raw.get("choices", [])
            if not choices:
                raise TransformError("OpenAI response has no choices")

            message = choices[0].get("message", {})
            text_content = message.get("content") or ""

            # Parse tool calls into structured ToolCallPart for executor tool_result 回路
            # 解析工具调用为结构化 ToolCallPart 供 executor tool_result 回路使用
            raw_tool_calls = message.get("tool_calls", [])
            tool_call_parts: list[ToolCallPart] = []
            for tc in raw_tool_calls:
                func = tc.get("function", {})
                try:
                    arguments = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    arguments = {}
                tool_call_parts.append(ToolCallPart(
                    tool_call_id=tc.get("id", ""),
                    tool_name=func.get("name", ""),
                    arguments=arguments,
                ))

            usage = raw.get("usage", {})
            tokens_used = usage.get("total_tokens", 0)

            return ProviderResult(
                subtask_id="",
                provider_id=self.provider_id,
                content=text_content,
                transformer_version=self.api_version,
                tokens_used=tokens_used,
                raw_response=raw,
                tool_calls=tool_call_parts,
            )
        except TransformError:
            raise
        except (KeyError, TypeError, IndexError) as exc:
            raise TransformError(
                f"Failed to parse OpenAI response: {exc}. Raw: {str(raw)[:200]}"
            ) from exc

    # -----------------------------------------------------------------------
    # Private conversion helpers / 私有转换辅助方法
    # -----------------------------------------------------------------------

    def _convert_message(
        self, msg: CanonicalMessage
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """
        将单条 CanonicalMessage 转换为 OpenAI message 格式
        Convert a single CanonicalMessage to OpenAI message format.

        Returns list when a tool message needs to be split into multiple OpenAI messages.
        当工具消息需要拆分时返回列表。
        """
        if msg.role.value == "system":
            text = " ".join(
                p.text for p in msg.content if isinstance(p, TextPart)
            )
            return {"role": "system", "content": text} if text else None

        if msg.role.value == "user":
            return self._convert_user_message(msg)

        if msg.role.value == "assistant":
            return self._convert_assistant_message(msg)

        if msg.role.value == "tool":
            return self._convert_tool_result_messages(msg)

        return None

    def _convert_user_message(self, msg: CanonicalMessage) -> dict[str, Any] | None:
        """用户消息转换 / Convert user message."""
        has_images = any(isinstance(p, ImagePart) for p in msg.content)

        if not has_images:
            # Simple text message
            text = " ".join(
                p.text for p in msg.content if isinstance(p, TextPart)
            )
            return {"role": "user", "content": text} if text else None

        # Multi-modal message with images
        # 包含图像的多模态消息
        content_parts: list[dict[str, Any]] = []
        for part in msg.content:
            if isinstance(part, TextPart) and part.text:
                content_parts.append({"type": "text", "text": part.text})
            elif isinstance(part, ImagePart):
                if part.url:
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": part.url},
                    })
                elif part.data:
                    data_url = f"data:{part.media_type};base64,{part.data}"
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    })

        return {"role": "user", "content": content_parts} if content_parts else None

    def _convert_assistant_message(self, msg: CanonicalMessage) -> dict[str, Any] | None:
        """助手消息转换 / Convert assistant message."""
        text_parts = [p.text for p in msg.content if isinstance(p, TextPart) and p.text]
        tool_calls = [p for p in msg.content if isinstance(p, ToolCallPart)]

        result: dict[str, Any] = {"role": "assistant"}

        if text_parts:
            result["content"] = " ".join(text_parts)
        else:
            result["content"] = None  # OpenAI requires content key even when None

        if tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tc.tool_name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in tool_calls
            ]

        return result

    def _convert_tool_result_messages(
        self, msg: CanonicalMessage
    ) -> list[dict[str, Any]]:
        """
        工具结果消息转换 — 每个 ToolResultPart 变为独立的 OpenAI tool message
        Convert tool result message — each ToolResultPart becomes a separate OpenAI tool message.
        """
        results = []
        for part in msg.content:
            if isinstance(part, ToolResultPart):
                results.append({
                    "role": "tool",
                    "tool_call_id": part.tool_call_id,
                    "content": part.content,
                })
        return results
