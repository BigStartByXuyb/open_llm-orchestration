"""
多租户上下文注入中间件
Multi-tenant context injection middleware.

Layer 1: Only imports from shared/.

职责 / Responsibilities:
  - 从 request.state（由 AuthMiddleware 设置）读取 tenant_id 和 user_id
    Read tenant_id and user_id from request.state (set by AuthMiddleware)
  - 创建 RunContext 并注入 request.state.run_context
    Create RunContext and inject into request.state.run_context
  - 生成 trace_id（UUID4）和 task_id 占位符
    Generate trace_id (UUID4) and task_id placeholder

必须在 AuthMiddleware 之后执行（依赖 request.state.tenant_id）。
Must run after AuthMiddleware (depends on request.state.tenant_id).
"""

from __future__ import annotations

import uuid
import logging
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from orchestration.shared.types import RunContext

logger = logging.getLogger(__name__)

_SKIP_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})


class TenantMiddleware(BaseHTTPMiddleware):
    """
    多租户上下文注入中间件
    Multi-tenant context injection middleware.
    """

    def __init__(self, app: Any) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        tenant_id: str = getattr(request.state, "tenant_id", "")
        user_id: str = getattr(request.state, "user_id", "")

        if tenant_id:
            # Build RunContext for this request
            # 为本次请求构建 RunContext
            context = RunContext(
                tenant_id=tenant_id,
                session_id="",   # filled in by route handler / 由路由处理器填充
                task_id="",      # filled in by route handler / 由路由处理器填充
                trace_id=str(uuid.uuid4()),
                user_id=user_id,
            )
            request.state.run_context = context

        return await call_next(request)
