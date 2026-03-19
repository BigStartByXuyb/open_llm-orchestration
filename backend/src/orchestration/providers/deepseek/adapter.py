"""
DeepSeekAdapter — DeepSeek API 异步 HTTP 客户端（OpenAI 兼容端点）
DeepSeekAdapter — Async HTTP client for DeepSeek API (OpenAI-compatible endpoint).

Layer 4: Only imports from shared/ and providers/_base_http.py.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from orchestration.shared.enums import ProviderID
from orchestration.shared.types import RunContext, StreamChunk
from orchestration.providers._base_http import BaseHttpAdapter
from orchestration.providers._streaming import parse_openai_sse_stream  # shared SSE parser, same format as OpenAI


class DeepSeekAdapter(BaseHttpAdapter):
    """
    DeepSeek API 异步适配器（复用 OpenAI SSE 解析器）
    Async adapter for DeepSeek API (reuses OpenAI SSE parser).
    """

    BASE_URL = "https://api.deepseek.com"
    DEFAULT_TIMEOUT = 120.0  # DeepSeek-R1 reasoning can take longer / 推理模型可能更慢

    provider_id: ProviderID = ProviderID.DEEPSEEK

    def _build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def call(self, payload: dict[str, Any], context: RunContext) -> dict[str, Any]:
        """调用 DeepSeek Chat API / Call DeepSeek Chat API."""
        return await self._post("/v1/chat/completions", payload, context)

    async def stream(
        self,
        payload: dict[str, Any],
        context: RunContext,
    ) -> AsyncIterator[StreamChunk]:
        """流式调用 DeepSeek API（与 OpenAI 相同 SSE 格式）/ Streaming call."""
        stream_payload = {**payload, "stream": True}
        client = self._get_client()

        async with client.stream("POST", "/v1/chat/completions", json=stream_payload) as response:
            if response.status_code >= 400:
                self._handle_response(response)
            async for chunk in parse_openai_sse_stream(response, str(self.provider_id)):
                yield chunk
