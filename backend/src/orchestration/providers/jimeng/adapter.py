"""
JimengAdapter — 极梦图像生成 API 异步 HTTP 客户端
JimengAdapter — Async HTTP client for Jimeng image generation API.

Layer 4: Only imports from shared/ and providers/_base_http.py.

支持双模式认证 / Dual-mode authentication:
  AUTH_MODE="bearer"          — 即梦 AI 开放平台 Bearer token（默认）
  AUTH_MODE="volcano_signing" — 火山引擎账号 HMAC-SHA256 每次请求动态签名

Image generation is synchronous (no polling needed for standard mode).
图像生成是同步的（标准模式无需轮询）。
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from orchestration.shared.enums import ProviderID
from orchestration.shared.types import RunContext, StreamChunk
from orchestration.providers._base_http import BaseHttpAdapter
from orchestration.providers.jimeng.config import JimengConfig
from orchestration.providers.jimeng.signing import build_volcano_auth_headers

# Volcengine API 端点常量 / Volcengine API endpoint constants
_ACTION_PATH = "/?Action=CVProcess&Version=2022-08-31"
_SIGN_PATH = "/"
_SIGN_QUERY = "Action=CVProcess&Version=2022-08-31"


class JimengAdapter(BaseHttpAdapter):
    """
    极梦图像生成 API 异步适配器（同步生成，无流式支持）
    Async adapter for Jimeng image generation API (synchronous generation, no streaming).

    认证模式由 JimengConfig.AUTH_MODE 控制：
    Authentication mode is controlled by JimengConfig.AUTH_MODE:
      "bearer"          — Authorization: Bearer {api_key}（客户端级别，创建时设置）
      "volcano_signing" — X-Date + Authorization HMAC-SHA256（每次请求动态生成）
    """

    BASE_URL = "https://visual.volcengineapi.com"
    DEFAULT_TIMEOUT = 60.0

    provider_id: ProviderID = ProviderID.JIMENG

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        config: JimengConfig | None = None,
    ) -> None:
        """
        初始化适配器。可直接传入 api_key（向后兼容），或传入完整 JimengConfig。
        Initialize adapter. Pass api_key directly (backward-compatible) or a full JimengConfig.
        """
        if config is not None:
            self._config = config
        else:
            # api_key 参数覆盖环境变量，保持向后兼容
            # api_key parameter overrides env var, maintaining backward compatibility
            kwargs: dict[str, Any] = {}
            if api_key:
                kwargs["API_KEY"] = api_key
            self._config = JimengConfig(**kwargs)

        super().__init__(
            api_key=self._config.API_KEY,
            base_url=base_url or self._config.BASE_URL,
        )

    def _build_headers(self) -> dict[str, str]:
        """
        构建客户端级别请求头。
        Build client-level request headers.

        bearer 模式：返回 Authorization Bearer（写入 httpx 客户端，对所有请求生效）
        volcano_signing 模式：仅返回 Content-Type（Authorization 在每次请求时动态计算）
        """
        if self._config.AUTH_MODE == "volcano_signing":
            # 签名头由 call() 每次请求动态生成，此处不设置 Authorization
            # Signing headers are generated per-request in call(), not set here
            return {"Content-Type": "application/json"}
        # Default: bearer token
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def call(self, payload: dict[str, Any], context: RunContext) -> dict[str, Any]:
        """
        调用极梦图像生成 API
        Call Jimeng image generation API.

        volcano_signing 模式下，每次调用前动态计算 HMAC-SHA256 签名。
        In volcano_signing mode, HMAC-SHA256 signature is computed fresh per call.
        """
        extra_headers: dict[str, str] | None = None

        if self._config.AUTH_MODE == "volcano_signing":
            # 序列化请求体以计算签名（与 httpx json= 序列化保持一致）
            # Serialize body for signing (consistent with httpx json= serialization)
            body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            signing_headers = build_volcano_auth_headers(
                method="POST",
                path=_SIGN_PATH,
                body=body_bytes,
                access_key=self._config.ACCESS_KEY,
                secret_key=self._config.SECRET_KEY,
                query_string=_SIGN_QUERY,
            )
            # Content-Type 已在客户端头中设置，只传递认证相关头
            # Content-Type is already in client headers; only pass auth-related headers
            extra_headers = {k: v for k, v in signing_headers.items() if k != "Content-Type"}

        return await self._post(
            _ACTION_PATH,
            payload,
            context,
            extra_headers=extra_headers,
        )

    async def stream(
        self,
        payload: dict[str, Any],
        context: RunContext,
    ) -> AsyncIterator[StreamChunk]:
        """
        极梦不支持流式输出 — 退化为同步调用后返回单块结果
        Jimeng doesn't support streaming — falls back to sync call and yields one chunk.
        """
        result = await self.call(payload, context)
        data = result.get("data", {})
        urls = data.get("image_urls", [])
        content = urls[0] if urls else ""
        yield StreamChunk(delta=content, is_final=True)
