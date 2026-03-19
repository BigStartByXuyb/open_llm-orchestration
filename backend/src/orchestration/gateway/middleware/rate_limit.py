"""
Redis 滑动窗口限流中间件
Redis sliding-window rate-limit middleware.

Layer 1: Only imports from shared/ and gateway/deps.

职责 / Responsibilities:
  - 每个租户每分钟请求数限制（滑动窗口，基于 Redis Sorted Set）
    Per-tenant per-minute request rate limit (sliding window via Redis Sorted Set)
  - 超出限制时返回 429
    Return 429 when limit exceeded
  - 跳过 /health 端点
    Skip /health endpoint
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from orchestration.shared.config import Settings, get_settings

logger = logging.getLogger(__name__)

_SKIP_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Redis 滑动窗口限流中间件
    Redis sliding-window rate-limit middleware.

    Reads tenant_id from request.state (injected by AuthMiddleware).
    从 request.state 读取 tenant_id（由 AuthMiddleware 注入）。
    """

    def __init__(self, app: Any, settings: Settings | None = None) -> None:
        super().__init__(app)
        self._settings = settings or get_settings()

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        tenant_id: str = getattr(request.state, "tenant_id", "")
        if not tenant_id:
            # No tenant_id means auth middleware skipped or failed
            # Let the request through; auth middleware already handles this
            return await call_next(request)

        # Access rate limit store from app container
        container = getattr(request.app.state, "container", None)
        if container is None:
            return await call_next(request)

        store = container.make_rate_limit_store()
        allowed = await store.check_and_record(tenant_id)

        if not allowed:
            logger.warning("Rate limit exceeded for tenant: %s", tenant_id)
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "code": "rate_limit_exceeded",
                    "detail": f"Max {self._settings.RATE_LIMIT_REQUESTS_PER_MINUTE} requests/minute",
                },
            )

        return await call_next(request)
