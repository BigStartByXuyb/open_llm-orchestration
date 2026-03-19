"""
GeminiAdapter — Google Gemini API 异步 HTTP 客户端
GeminiAdapter — Async HTTP client for Google Gemini API.

Layer 4: Only imports from shared/ and providers/_base_http.py.

Gemini uses API key as query parameter, not a header.
Gemini 使用 API key 作为查询参数，而非请求头。
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import httpx

from orchestration.shared.enums import ProviderID
from orchestration.shared.errors import ProviderError, ProviderUnavailable
from orchestration.shared.types import RunContext, StreamChunk
from orchestration.providers._base_http import BaseHttpAdapter


class GeminiAdapter(BaseHttpAdapter):
    """
    Google Gemini API 异步适配器
    Async adapter for Google Gemini API.

    Note: Gemini passes API key as ?key= query param (not Authorization header).
    注意：Gemini 通过 ?key= 查询参数传递 API key（非 Authorization 头）。
    """

    BASE_URL = "https://generativelanguage.googleapis.com"
    DEFAULT_TIMEOUT = 60.0

    provider_id: ProviderID = ProviderID.GEMINI

    def _build_headers(self) -> dict[str, str]:
        # No auth header — Gemini uses API key as query param
        # 无认证头 — Gemini 使用查询参数
        return {"Content-Type": "application/json"}

    def _api_key_params(self) -> dict[str, str]:
        """返回包含 API key 的查询参数 / Return query params containing API key."""
        return {"key": self.api_key} if self.api_key else {}

    async def call(
        self, payload: dict[str, Any], context: RunContext
    ) -> dict[str, Any]:
        """
        调用 Gemini generateContent API
        Call Gemini generateContent API.

        Model name is embedded in the URL path.
        模型名称嵌入在 URL 路径中。
        """
        model = payload.pop("model", "gemini-2.0-flash") if "model" in payload else "gemini-2.0-flash"
        path = f"/v1beta/models/{model}:generateContent"
        client = self._get_client()

        try:
            response = await client.post(
                path,
                json=payload,
                params=self._api_key_params(),
            )
            return self._handle_response(response)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(
                f"Gemini request timeout", provider_id=str(self.provider_id)
            ) from exc
        except httpx.NetworkError as exc:
            raise ProviderUnavailable(
                f"Gemini network error: {exc}", provider_id=str(self.provider_id)
            ) from exc

    async def stream(
        self,
        payload: dict[str, Any],
        context: RunContext,
    ) -> AsyncIterator[StreamChunk]:
        """
        流式调用 Gemini streamGenerateContent API
        Streaming call to Gemini streamGenerateContent API.
        """
        import json

        model = payload.pop("model", "gemini-2.0-flash") if "model" in payload else "gemini-2.0-flash"
        path = f"/v1beta/models/{model}:streamGenerateContent"
        client = self._get_client()
        params = {**self._api_key_params(), "alt": "sse"}

        async with client.stream("POST", path, json=payload, params=params) as response:
            if response.status_code >= 400:
                self._handle_response(response)

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

                    candidates = event.get("candidates", [])
                    if not candidates:
                        continue

                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        text = part.get("text", "")
                        if text:
                            yield StreamChunk(delta=text, is_final=False)

                    finish_reason = candidates[0].get("finishReason")
                    if finish_reason:
                        yield StreamChunk(delta="", is_final=True, metadata={"finish_reason": finish_reason})
                        return

            except httpx.StreamError as exc:
                raise ProviderUnavailable(
                    f"Gemini stream error: {exc}", provider_id=str(self.provider_id)
                ) from exc
