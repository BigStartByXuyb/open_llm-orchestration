"""
OpenAI-compatible SSE 流式响应解析工具
OpenAI-compatible SSE streaming response parser utility.

Layer 4 shared utility: usable by any provider that follows the OpenAI SSE format
(OpenAI, DeepSeek, etc.) without creating cross-provider imports.
Layer 4 共享工具：可供所有使用 OpenAI SSE 格式的 provider 使用，避免跨 provider 导入。

Only imports from shared/ and third-party libraries.
只导入 shared/ 和第三方库。
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from orchestration.shared.errors import ProviderUnavailable
from orchestration.shared.types import StreamChunk


async def parse_openai_sse_stream(
    response: httpx.Response,
    provider_id: str = "openai",
) -> AsyncIterator[StreamChunk]:
    """
    解析 OpenAI SSE 流式响应（OpenAI/DeepSeek 相同格式）
    Parse OpenAI SSE streaming response (same format for OpenAI and DeepSeek).

    SSE format / SSE 格式:
      data: {"choices": [{"delta": {"content": "..."}}]}
      data: [DONE]
    """
    try:
        async for line in response.aiter_lines():
            line = line.strip()
            if not line or not line.startswith("data: "):
                continue

            data_str = line[len("data: "):]
            if data_str == "[DONE]":
                yield StreamChunk(delta="", is_final=True)
                return

            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            choices = event.get("choices", [])
            if not choices:
                continue

            delta = choices[0].get("delta", {})
            content = delta.get("content", "")
            if content:
                yield StreamChunk(delta=content, is_final=False)

            # finish_reason signals stream end
            finish_reason = choices[0].get("finish_reason")
            if finish_reason:
                usage = event.get("usage", {})
                yield StreamChunk(
                    delta="",
                    is_final=True,
                    metadata={"finish_reason": finish_reason, "usage": usage},
                )
                return

    except httpx.StreamError as exc:
        raise ProviderUnavailable(
            f"{provider_id} stream error: {exc}", provider_id=provider_id
        ) from exc
