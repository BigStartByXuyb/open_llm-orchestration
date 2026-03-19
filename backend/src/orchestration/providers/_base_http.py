"""
BaseHttpAdapter — Provider Adapter 公共基类（内部使用）
BaseHttpAdapter — Internal base class for HTTP-based provider adapters.

Layer 4: Only imports from shared/. Not exported to other layers.
第 4 层：仅从 shared/ 导入，不对外层暴露。

Responsibilities / 职责:
  - Build and manage a shared httpx.AsyncClient
    构建并管理共享的 httpx.AsyncClient
  - Translate HTTP status codes to ProviderError subclasses
    将 HTTP 状态码翻译为 ProviderError 子类
  - Provide a consistent request/response cycle with timeout
    提供带超时的一致请求/响应周期
"""

from __future__ import annotations

from typing import Any

import httpx

from orchestration.shared.errors import AuthError, ProviderError, ProviderUnavailable, RateLimitError
from orchestration.shared.types import RunContext


class BaseHttpAdapter:
    """
    基于 httpx 的 Provider Adapter 基类
    Base class for httpx-based provider adapters.

    Each provider subclass sets:
    每个 provider 子类设置：
      - BASE_URL: API base URL
      - DEFAULT_TIMEOUT: request timeout in seconds
      - _build_headers(): returns auth headers for each request
    """

    BASE_URL: str = ""
    DEFAULT_TIMEOUT: float = 60.0

    def __init__(self, api_key: str, base_url: str = "") -> None:
        self.api_key = api_key
        self._base_url = base_url or self.BASE_URL
        # Client is created lazily to allow testing without real network
        # 客户端懒创建，允许测试时不连接真实网络
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """
        获取（或懒创建）httpx 异步客户端
        Get (or lazily create) the httpx async client.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self.DEFAULT_TIMEOUT,
                headers=self._build_headers(),
            )
        return self._client

    def _build_headers(self) -> dict[str, str]:
        """
        构建请求头（子类覆盖以添加认证）
        Build request headers (subclasses override to add auth).
        """
        return {"Content-Type": "application/json"}

    async def _post(
        self,
        path: str,
        payload: dict[str, Any],
        context: RunContext,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        发起 POST 请求，自动处理 HTTP 错误
        Make a POST request with automatic HTTP error handling.

        Translates HTTP errors into ProviderError subclasses.
        将 HTTP 错误翻译为 ProviderError 子类。
        """
        client = self._get_client()
        headers = extra_headers or {}

        try:
            response = await client.post(path, json=payload, headers=headers)
            return self._handle_response(response)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(
                f"Request timeout after {self.DEFAULT_TIMEOUT}s",
                provider_id=str(getattr(self, "provider_id", "")),
            ) from exc
        except httpx.NetworkError as exc:
            raise ProviderUnavailable(
                f"Network error: {exc}",
                provider_id=str(getattr(self, "provider_id", "")),
            ) from exc

    async def _get(
        self,
        path: str,
        context: RunContext,
        *,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """
        发起 GET 请求（用于轮询等场景）
        Make a GET request (used for polling etc.).
        """
        client = self._get_client()
        headers = extra_headers or {}

        try:
            response = await client.get(path, params=params, headers=headers)
            return self._handle_response(response)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(
                f"Request timeout",
                provider_id=str(getattr(self, "provider_id", "")),
            ) from exc
        except httpx.NetworkError as exc:
            raise ProviderUnavailable(
                f"Network error: {exc}",
                provider_id=str(getattr(self, "provider_id", "")),
            ) from exc

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """
        处理 HTTP 响应，将错误状态码翻译为 ProviderError 子类
        Handle HTTP response, translating error status codes to ProviderError subclasses.
        """
        provider_id = str(getattr(self, "provider_id", ""))

        if response.status_code == 401 or response.status_code == 403:
            raise AuthError(
                f"Authentication failed (HTTP {response.status_code})",
                status_code=response.status_code,
                provider_id=provider_id,
            )

        if response.status_code == 429:
            retry_after = float(response.headers.get("retry-after", 0))
            raise RateLimitError(
                f"Rate limit exceeded (HTTP 429)",
                retry_after=retry_after,
                provider_id=provider_id,
            )

        if response.status_code >= 500:
            raise ProviderUnavailable(
                f"Provider unavailable (HTTP {response.status_code}): {response.text[:200]}",
                status_code=response.status_code,
                provider_id=provider_id,
            )

        if response.status_code >= 400:
            raise ProviderError(
                f"Client error (HTTP {response.status_code}): {response.text[:200]}",
                status_code=response.status_code,
                provider_id=provider_id,
            )

        try:
            return response.json()
        except Exception as exc:
            raise ProviderError(
                f"Failed to parse response JSON: {exc}",
                provider_id=provider_id,
            ) from exc

    async def aclose(self) -> None:
        """关闭 httpx 客户端 / Close the httpx client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> "BaseHttpAdapter":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()
