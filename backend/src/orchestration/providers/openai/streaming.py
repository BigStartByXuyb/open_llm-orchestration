"""
OpenAI SSE 流式响应处理
OpenAI SSE streaming response handler.

Layer 4: Only imports from shared/.

OpenAI streaming format / OpenAI 流格式:
  data: {"choices": [{"delta": {"content": "..."}}]}
  data: [DONE]
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from orchestration.shared.errors import ProviderUnavailable
from orchestration.shared.types import StreamChunk
from orchestration.providers._streaming import parse_openai_sse_stream  # noqa: F401


async def parse_openai_stream(
    response: httpx.Response,
    provider_id: str = "openai",
) -> AsyncIterator[StreamChunk]:
    """
    解析 OpenAI SSE 流式响应
    Parse OpenAI SSE streaming response.
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

            # finish_reason signals end
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
        raise ProviderUnavailable(f"OpenAI stream error: {exc}", provider_id=provider_id) from exc
