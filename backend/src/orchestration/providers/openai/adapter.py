"""
OpenAIAdapter — OpenAI Chat Completions API 异步 HTTP 客户端
OpenAIAdapter — Async HTTP client for OpenAI Chat Completions API.

Layer 4: Only imports from shared/ and providers/_base_http.py.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from orchestration.shared.enums import ProviderID
from orchestration.shared.types import RunContext, StreamChunk
from orchestration.providers._base_http import BaseHttpAdapter
from orchestration.providers.openai.streaming import parse_openai_stream


class OpenAIAdapter(BaseHttpAdapter):
    """OpenAI Chat Completions API 异步适配器 / Async adapter for OpenAI Chat Completions API."""

    BASE_URL = "https://api.openai.com"
    DEFAULT_TIMEOUT = 60.0

    provider_id: ProviderID = ProviderID.OPENAI

    def _build_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def call(self, payload: dict[str, Any], context: RunContext) -> dict[str, Any]:
        """
        调用 OpenAI Chat Completions API
        Call OpenAI Chat Completions API.
        """
        return await self._post("/v1/chat/completions", payload, context)

    async def stream(
        self,
        payload: dict[str, Any],
        context: RunContext,
    ) -> AsyncIterator[StreamChunk]:
        """流式调用 OpenAI Chat Completions API / Streaming call."""
        stream_payload = {**payload, "stream": True}
        client = self._get_client()

        async with client.stream("POST", "/v1/chat/completions", json=stream_payload) as response:
            self._handle_response(response) if response.status_code >= 400 else None
            async for chunk in parse_openai_stream(response, str(self.provider_id)):
                yield chunk
