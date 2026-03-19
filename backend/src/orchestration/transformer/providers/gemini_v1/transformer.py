"""
GeminiV1Transformer — Google Gemini API v1 格式转换器
GeminiV1Transformer — Converts canonical messages to Google Gemini API format.

Layer 3: Only imports from shared/ and transformer/.
第 3 层：仅从 shared/ 和 transformer/ 导入。

Gemini API has distinct conventions / Gemini API 有独特约定:
  - Uses "contents" array (not "messages")
    使用 "contents" 数组（非 "messages"）
  - Roles: "user" and "model" (not "assistant")
    角色："user" 和 "model"（非 "assistant"）
  - System instruction is a separate top-level field "system_instruction"
    System 指令是独立的顶级字段 "system_instruction"
  - Images use inline_data (base64) or file_data (URI)
    图像使用 inline_data（base64）或 file_data（URI）
  - Tool calling uses functionDeclarations / functionCall / functionResponse
    工具调用使用 functionDeclarations / functionCall / functionResponse
  - Tool messages use role="user" with functionResponse parts
    工具消息使用 role="user" 包含 functionResponse 部分
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


class GeminiV1Transformer(BaseTransformer):
    """
    Google Gemini API v1 格式转换器
    Transformer for Google's Gemini API (gemini-* models).
    """

    provider_id: ProviderID = ProviderID.GEMINI
    api_version: str = "v1"

    DEFAULT_MODEL = "gemini-2.0-flash"
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
        将 CanonicalMessage 列表转换为 Gemini API 请求格式
        Convert to Gemini generateContent API request format.
        """
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role.value == "system":
                for part in msg.content:
                    if isinstance(part, TextPart):
                        system_parts.append(part.text)
            else:
                content_item = self._convert_message(msg)
                if content_item is not None:
                    contents.append(content_item)

        if not contents:
            raise TransformError("Gemini API requires at least one non-system message")

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": self.max_tokens,
            },
        }

        if system_parts:
            payload["system_instruction"] = {
                "parts": [{"text": "\n\n".join(system_parts)}]
            }

        return payload

    def transform_tools(self, tools: list[CanonicalTool]) -> list[dict[str, Any]]:
        """
        将工具定义转换为 Gemini functionDeclarations 格式
        Convert tool definitions to Gemini functionDeclarations format.
        """
        if not tools:
            return []
        return [
            {
                "function_declarations": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    }
                    for tool in tools
                ]
            }
        ]

    def parse_response(self, raw: dict[str, Any]) -> ProviderResult:
        """
        解析 Gemini generateContent API 响应
        Parse Gemini generateContent API response.

        Response format / 响应格式:
        {
          "candidates": [{
            "content": {"parts": [{"text": "..."}, {"functionCall": {...}}], "role": "model"},
          }],
          "usageMetadata": {"promptTokenCount": N, "candidatesTokenCount": M}
        }
        """
        try:
            candidates = raw.get("candidates", [])
            if not candidates:
                raise TransformError("Gemini response has no candidates")

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])

            text_chunks: list[str] = []
            for part in parts:
                if "text" in part:
                    text_chunks.append(part["text"])
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    text_chunks.append(
                        f"[function_call: {fc.get('name')}({json.dumps(fc.get('args', {}))})]"
                    )

            text = "".join(text_chunks)

            usage = raw.get("usageMetadata", {})
            tokens_used = (
                usage.get("promptTokenCount", 0) + usage.get("candidatesTokenCount", 0)
            )

            return ProviderResult(
                subtask_id="",
                provider_id=self.provider_id,
                content=text,
                transformer_version=self.api_version,
                tokens_used=tokens_used,
                raw_response=raw,
            )
        except TransformError:
            raise
        except (KeyError, TypeError, IndexError) as exc:
            raise TransformError(
                f"Failed to parse Gemini response: {exc}. Raw: {str(raw)[:200]}"
            ) from exc

    def _convert_message(self, msg: CanonicalMessage) -> dict[str, Any] | None:
        """
        将单条 CanonicalMessage 转换为 Gemini content 格式
        Convert a single CanonicalMessage to Gemini content format.
        """
        # Gemini roles: "user" or "model"
        # Gemini 角色："user" 或 "model"
        if msg.role.value == "assistant":
            role = "model"
        elif msg.role.value in ("user", "tool"):
            role = "user"
        else:
            return None

        gemini_parts: list[dict[str, Any]] = []

        for part in msg.content:
            if isinstance(part, TextPart) and part.text:
                gemini_parts.append({"text": part.text})

            elif isinstance(part, ImagePart):
                if part.data:
                    gemini_parts.append({
                        "inline_data": {
                            "mime_type": part.media_type,
                            "data": part.data,
                        }
                    })
                elif part.url:
                    gemini_parts.append({
                        "file_data": {
                            "mime_type": part.media_type,
                            "file_uri": part.url,
                        }
                    })

            elif isinstance(part, ToolCallPart):
                gemini_parts.append({
                    "functionCall": {
                        "name": part.tool_name,
                        "args": part.arguments,
                    }
                })

            elif isinstance(part, ToolResultPart):
                # Tool results in Gemini use functionResponse with role="user"
                # Gemini 中工具结果使用 functionResponse，role="user"
                gemini_parts.append({
                    "functionResponse": {
                        "name": part.tool_call_id,
                        "response": {"content": part.content},
                    }
                })

        return {"role": role, "parts": gemini_parts} if gemini_parts else None
