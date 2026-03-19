"""
AnthropicAdapter — Anthropic Messages API 异步 HTTP 客户端
AnthropicAdapter — Async HTTP client for Anthropic Messages API.

Layer 4: Only imports from shared/ and providers/_base_http.py.
第 4 层：仅从 shared/ 和 providers/_base_http.py 导入。

Error boundary / 错误边界:
  - HTTP 4xx/5xx → ProviderError subclasses (AuthError, RateLimitError, ProviderUnavailable)
    HTTP 4xx/5xx → ProviderError 子类
  - Does NOT handle TransformError — that's the executor's responsibility
    不处理 TransformError — 那是 executor 的责任
  - Does NOT touch CanonicalMessage — only deals with raw dicts
    不接触 CanonicalMessage — 只处理原始 dict
"""

from __future__ import annotations

from typing import Any, AsyncIterator

from orchestration.shared.enums import ProviderID
from orchestration.shared.types import RunContext, StreamChunk
from orchestration.providers._base_http import BaseHttpAdapter
from orchestration.providers.anthropic.streaming import parse_anthropic_stream


class AnthropicAdapter(BaseHttpAdapter):
    """
    Anthropic Messages API 异步适配器
    Async adapter for Anthropic Messages API.
    """

    BASE_URL = "https://api.anthropic.com"
    DEFAULT_TIMEOUT = 120.0

    provider_id: ProviderID = ProviderID.ANTHROPIC

    # Anthropic requires an API version header
    # Anthropic 需要 API 版本请求头
    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, api_key: str, base_url: str = "") -> None:
        super().__init__(api_key=api_key, base_url=base_url)

    def _build_headers(self) -> dict[str, str]:
        """构建 Anthropic 认证头 / Build Anthropic auth headers."""
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
        }

    async def call(self, payload: dict[str, Any], context: RunContext) -> dict[str, Any]:
        """
        发起同步调用 Anthropic Messages API
        Make a synchronous call to Anthropic Messages API.

        Args / 参数:
            payload: Provider-specific request dict from AnthropicV3Transformer.transform()
                     来自 AnthropicV3Transformer.transform() 的 provider 专有请求 dict
            context: Run context containing tenant/session/trace IDs
                     包含租户/会话/追踪 ID 的运行上下文

        Returns / 返回:
            Raw JSON response dict from Anthropic.
            来自 Anthropic 的原始 JSON 响应 dict。

        Raises / 抛出:
            AuthError: HTTP 401/403
            RateLimitError: HTTP 429
            ProviderUnavailable: HTTP 5xx or network error
            ProviderError: Other HTTP 4xx
        """
        return await self._post("/v1/messages", payload, context)

    async def stream(
        self,
        payload: dict[str, Any],
        context: RunContext,
    ) -> AsyncIterator[StreamChunk]:
        """
        发起流式调用 Anthropic Messages API（SSE）
        Make a streaming call to Anthropic Messages API (SSE).

        Adds stream=True to the payload automatically.
        自动向 payload 添加 stream=True。
        """
        stream_payload = {**payload, "stream": True}
        client = self._get_client()

        async with client.stream("POST", "/v1/messages", json=stream_payload) as response:
            # Check for HTTP errors before starting to read the stream
            # 在读取流之前检查 HTTP 错误
            self._handle_response_status(response)
            async for chunk in parse_anthropic_stream(response, str(self.provider_id)):
                yield chunk

    def _handle_response_status(self, response: "Any") -> None:
        """
        检查流式响应的 HTTP 状态（不读取 body）
        Check streaming response HTTP status without reading body.
        """
        from orchestration.shared.errors import AuthError, RateLimitError, ProviderUnavailable, ProviderError
        provider_id = str(self.provider_id)
        status = response.status_code
        if status == 401 or status == 403:
            raise AuthError(f"Authentication failed (HTTP {status})", status_code=status, provider_id=provider_id)
        if status == 429:
            retry_after = float(response.headers.get("retry-after", 0))
            raise RateLimitError(f"Rate limit exceeded", retry_after=retry_after, provider_id=provider_id)
        if status >= 500:
            raise ProviderUnavailable(f"Provider unavailable (HTTP {status})", status_code=status, provider_id=provider_id)
        if status >= 400:
            raise ProviderError(f"Client error (HTTP {status})", status_code=status, provider_id=provider_id)
