"""
OTel 追踪中间件 — 为每个请求注入 trace_id 并创建根 Span
OTel tracing middleware — inject trace_id into each request and create a root span.

Layer 1: Only imports from shared/ (and third-party libraries).

trace_id 传播规则 / trace_id propagation rules:
  1. 若请求携带 W3C traceparent 头 → 提取其 trace_id
     If request has W3C traceparent header → extract its trace_id
  2. 否则 → 从新建 OTel span 中取 trace_id
     Otherwise → take trace_id from the newly created OTel span
  3. 注入到 request.state.trace_id，并写入响应头 x-trace-id
     Inject into request.state.trace_id, and write to response header x-trace-id
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import Request, Response
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger(__name__)

# Paths that bypass tracing / 跳过追踪的路径
_SKIP_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})


def _parse_traceparent(header: str) -> str | None:
    """
    解析 W3C traceparent 头，提取 trace_id（32 位小写十六进制字符串）
    Parse W3C traceparent header, extract trace_id (32-char lowercase hex string).

    Format: version-trace_id-parent_id-flags
    Example: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
    """
    parts = header.split("-")
    if len(parts) != 4:
        return None
    version, trace_id_hex, _parent_id, _flags = parts
    if version != "00" or len(trace_id_hex) != 32:
        return None
    try:
        int(trace_id_hex, 16)  # validate hex
        return trace_id_hex.lower()
    except ValueError:
        return None


class TracingMiddleware(BaseHTTPMiddleware):
    """
    OTel 追踪中间件
    OTel tracing middleware.

    每个请求:
      - 提取或生成 trace_id（W3C traceparent 优先）
        Extract or generate trace_id (W3C traceparent takes precedence)
      - 注入 request.state.trace_id 供 RunContext 使用
        Inject request.state.trace_id for RunContext consumption
      - 创建 OTel SERVER span
        Create an OTel SERVER span
      - 写入 x-trace-id 到响应头
        Write x-trace-id to response header
    """

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._tracer = trace.get_tracer("orchestration.gateway", "0.1.0")

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip tracing for health check and documentation paths
        # 跳过健康检查和文档路径
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        # ① Try to extract trace_id from W3C traceparent header
        # ① 尝试从 W3C traceparent 头提取 trace_id
        incoming_traceparent = request.headers.get("traceparent", "")
        trace_id: str | None = (
            _parse_traceparent(incoming_traceparent) if incoming_traceparent else None
        )

        # ② Create an OTel span for this request
        # ② 为此请求创建 OTel span
        with self._tracer.start_as_current_span(
            f"{request.method} {request.url.path}",
            kind=trace.SpanKind.SERVER,
        ) as span:
            # ③ If no traceparent, derive trace_id from the OTel span
            # ③ 若无 traceparent，从 OTel span 获取 trace_id
            if trace_id is None:
                span_ctx = span.get_span_context()
                trace_id = (
                    format(span_ctx.trace_id, "032x")
                    if span_ctx.is_valid
                    else uuid.uuid4().hex
                )

            # ④ Inject trace_id into request.state for downstream (RunContext)
            # ④ 注入 trace_id 到 request.state，供下游（RunContext）使用
            request.state.trace_id = trace_id

            span.set_attribute("http.method", request.method)
            span.set_attribute("http.url", str(request.url))
            span.set_attribute("http.target", request.url.path)

            response = await call_next(request)

            span.set_attribute("http.status_code", response.status_code)

        # ⑤ Propagate trace_id to client for log correlation
        # ⑤ 传播 trace_id 到客户端用于日志关联
        response.headers["x-trace-id"] = trace_id
        return response
