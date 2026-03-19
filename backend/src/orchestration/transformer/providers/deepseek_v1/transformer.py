"""
DeepSeekV1Transformer — DeepSeek API v1 格式转换器
DeepSeekV1Transformer — Converts canonical messages to DeepSeek API format.

Layer 3: Only imports from shared/ and transformer/.
第 3 层：仅从 shared/ 和 transformer/ 导入。

DeepSeek is OpenAI-compatible but with key differences:
DeepSeek 兼容 OpenAI 格式，但有若干差异:
  - Only supports text (no image input for deepseek-chat)
    仅支持文本（deepseek-chat 不支持图像输入）
  - Different model names (deepseek-chat, deepseek-reasoner)
    不同的模型名称
  - tool calling is supported
    支持工具调用
  - No native streaming prefix, uses SSE same as OpenAI
    无原生流前缀，与 OpenAI 相同使用 SSE
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


class DeepSeekV1Transformer(BaseTransformer):
    """
    DeepSeek API v1 格式转换器（OpenAI 兼容）
    Transformer for DeepSeek API (OpenAI-compatible format).
    """

    provider_id: ProviderID = ProviderID.DEEPSEEK
    api_version: str = "v1"

    DEFAULT_MODEL = "deepseek-chat"
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
        将 CanonicalMessage 列表转换为 DeepSeek API 请求格式
        Convert to DeepSeek API request format (OpenAI-compatible).
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
            raise TransformError("DeepSeek API requires at least one message")

        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": api_messages,
        }

    def transform_tools(self, tools: list[CanonicalTool]) -> list[dict[str, Any]]:
        """
        将工具定义转换为 DeepSeek function calling 格式（与 OpenAI 相同）
        Convert tool definitions to DeepSeek function calling format (same as OpenAI).
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
        解析 DeepSeek API 响应（与 OpenAI 格式相同）
        Parse DeepSeek API response (same format as OpenAI).
        """
        try:
            choices = raw.get("choices", [])
            if not choices:
                raise TransformError("DeepSeek response has no choices")

            message = choices[0].get("message", {})
            text_content = message.get("content") or ""

            # Reasoning content (deepseek-reasoner specific)
            # 推理内容（deepseek-reasoner 专有）
            reasoning = message.get("reasoning_content")
            if reasoning:
                text_content = f"<reasoning>{reasoning}</reasoning>\n{text_content}"

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
                f"Failed to parse DeepSeek response: {exc}. Raw: {str(raw)[:200]}"
            ) from exc

    def _convert_message(
        self, msg: CanonicalMessage
    ) -> dict[str, Any] | list[dict[str, Any]] | None:
        """将单条 CanonicalMessage 转换为 DeepSeek message / Convert single message."""
        if msg.role.value == "system":
            text = " ".join(p.text for p in msg.content if isinstance(p, TextPart))
            return {"role": "system", "content": text} if text else None

        if msg.role.value == "user":
            # DeepSeek text-only: skip image parts, warn via metadata
            # DeepSeek 仅文本：跳过图像内容
            text_parts = [p.text for p in msg.content if isinstance(p, TextPart) and p.text]
            has_images = any(isinstance(p, ImagePart) for p in msg.content)

            if has_images:
                # Log skip via metadata — deepseek-chat doesn't support vision
                # 通过 metadata 记录跳过 — deepseek-chat 不支持图像
                text_parts.append("[Image not supported by DeepSeek text model]")

            text = " ".join(text_parts)
            return {"role": "user", "content": text} if text else None

        if msg.role.value == "assistant":
            text_parts = [p.text for p in msg.content if isinstance(p, TextPart) and p.text]
            tool_calls = [p for p in msg.content if isinstance(p, ToolCallPart)]

            result: dict[str, Any] = {"role": "assistant", "content": " ".join(text_parts) or None}
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

        if msg.role.value == "tool":
            return [
                {
                    "role": "tool",
                    "tool_call_id": p.tool_call_id,
                    "content": p.content,
                }
                for p in msg.content
                if isinstance(p, ToolResultPart)
            ]

        return None
