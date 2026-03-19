"""
Anthropic SSE 流式响应处理
Anthropic SSE streaming response handler.

Layer 4: Only imports from shared/.
第 4 层：仅从 shared/ 导入。

Anthropic streaming format / Anthropic 流格式:
  data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "..."}}
  data: {"type": "message_delta", "usage": {"output_tokens": N}}
  data: [DONE]  ← not used by Anthropic, ends with message_stop event
"""

from __future__ import annotations

from typing import AsyncIterator

import httpx

from orchestration.shared.errors import ProviderError, ProviderUnavailable
from orchestration.shared.types import StreamChunk


async def parse_anthropic_stream(
    response: httpx.Response,
    provider_id: str = "anthropic",
) -> AsyncIterator[StreamChunk]:
    """
    解析 Anthropic SSE 流式响应，逐块产出 StreamChunk
    Parse Anthropic SSE streaming response, yielding StreamChunks.

    Yields / 产出:
        StreamChunk with delta text; final chunk has is_final=True.
        包含增量文本的 StreamChunk；最后一块 is_final=True。

    Raises / 抛出:
        ProviderError: If the stream is malformed or abruptly terminated.
    """
    import json

    output_tokens = 0
    buffer = ""

    try:
        async for line in response.aiter_lines():
            line = line.strip()
            if not line:
                continue
            if not line.startswith("data: "):
                continue

            data_str = line[len("data: "):]
            if data_str == "[DONE]":
                break

            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")

            if event_type == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        buffer += text
                        yield StreamChunk(delta=text, is_final=False)

            elif event_type == "message_delta":
                usage = event.get("usage", {})
                output_tokens = usage.get("output_tokens", 0)

            elif event_type == "message_stop":
                # Signal final chunk
                # 信号最终块
                yield StreamChunk(
                    delta="",
                    is_final=True,
                    metadata={"output_tokens": output_tokens},
                )
                return

    except httpx.StreamError as exc:
        raise ProviderUnavailable(
            f"Anthropic stream error: {exc}",
            provider_id=provider_id,
        ) from exc
