"""
Prometheus 指标中间件
Prometheus metrics middleware.

Layer 1: Only imports from shared/ and gateway/.

暴露的指标 / Exposed metrics:
  requests_total{method, path, status}    Counter  — HTTP 请求总数
  request_duration_seconds{method, path}  Histogram — 请求延迟
  provider_calls_total{provider_id}       Counter  — Provider 调用次数（由 executor 侧更新）
  active_tasks                            Gauge    — 当前活跃任务数（由 engine 侧更新）

使用方式 / Usage:
  from orchestration.gateway.middleware.metrics import MetricsMiddleware, METRICS_REGISTRY
  app.add_middleware(MetricsMiddleware)

  # 在 executor 中记录 provider 调用
  from orchestration.gateway.middleware.metrics import record_provider_call
  record_provider_call("anthropic")

  # 在 engine 中记录活跃任务
  from orchestration.gateway.middleware.metrics import active_tasks_gauge
  active_tasks_gauge.inc()
  active_tasks_gauge.dec()

GET /metrics 端点需在 app.py 中单独注册。
GET /metrics endpoint must be registered separately in app.py.
"""

from __future__ import annotations

import re
import time
from typing import Any

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST,
    REGISTRY as DEFAULT_REGISTRY,
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ---------------------------------------------------------------------------
# Shared registry
# 共享注册表
# ---------------------------------------------------------------------------

# Use Prometheus' default global registry.
# 使用 Prometheus 默认全局注册表。
# Tests that need isolation can build their own CollectorRegistry.
METRICS_REGISTRY: CollectorRegistry = DEFAULT_REGISTRY

# ---------------------------------------------------------------------------
# Metric definitions
# 指标定义
# ---------------------------------------------------------------------------

requests_total = Counter(
    "orch_requests_total",
    "Total HTTP requests handled by the gateway",
    ["method", "path", "status"],
    registry=METRICS_REGISTRY,
)

request_duration_seconds = Histogram(
    "orch_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=METRICS_REGISTRY,
)

provider_calls_total = Counter(
    "orch_provider_calls_total",
    "Total provider adapter calls (incremented by ParallelExecutor)",
    ["provider_id"],
    registry=METRICS_REGISTRY,
)

active_tasks_gauge = Gauge(
    "orch_active_tasks",
    "Number of currently active orchestration tasks",
    registry=METRICS_REGISTRY,
)

subtask_duration_seconds = Histogram(
    "orch_subtask_duration_seconds",
    "Subtask execution latency in seconds",
    ["capability", "provider"],
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
    registry=METRICS_REGISTRY,
)

subtask_total = Counter(
    "orch_subtask_total",
    "Total subtask executions",
    ["capability", "status"],
    registry=METRICS_REGISTRY,
)

tool_turns_total = Counter(
    "orch_tool_turns_total",
    "Total tool turns executed in ParallelExecutor",
    ["skill_id"],
    registry=METRICS_REGISTRY,
)

# ---------------------------------------------------------------------------
# Convenience helpers (called from executor / engine)
# 便捷辅助函数（由 executor / engine 调用）
# ---------------------------------------------------------------------------


def record_provider_call(provider_id: str) -> None:
    """
    记录一次 provider 调用（供 ParallelExecutor 调用）。
    Record one provider call (called by ParallelExecutor).
    """
    provider_calls_total.labels(provider_id=provider_id).inc()


# ---------------------------------------------------------------------------
# ASGI middleware
# ASGI 中间件
# ---------------------------------------------------------------------------

# Paths that should not be tracked per-path (e.g., health checks) to avoid
# cardinality explosion. These are still counted under a normalized path.
# 不按路径跟踪的端点（健康检查等），防止 cardinality 爆炸。
_SKIP_PATH_TRACKING = frozenset({"/health", "/healthz", "/readyz", "/metrics"})


def _normalize_path(path: str) -> str:
    """
    将路径规范化以降低 cardinality（替换 UUID/数字 ID 段）。
    Normalize path to reduce cardinality (replace UUID/numeric ID segments).

    Examples:
        /tasks/abc-123      → /tasks/{id}
        /sessions/42        → /sessions/{id}
        /documents/some-id  → /documents/{id}
    """
    # Replace UUID segments
    path = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "{id}",
        path,
    )
    # Replace bare numeric IDs
    path = re.sub(r"(?<=/)\d+(?=/|$)", "{id}", path)
    return path


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Prometheus 指标采集 ASGI 中间件。
    Prometheus metrics collection ASGI middleware.

    对每个请求：
      - 记录 requests_total（method, normalized_path, status_code）
      - 记录 request_duration_seconds（method, normalized_path）
    For each request:
      - Increment requests_total with method, normalized_path, status_code
      - Observe request_duration_seconds with method, normalized_path
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        elapsed = time.monotonic() - start

        method = request.method
        path = _normalize_path(request.url.path)
        status = str(response.status_code)

        requests_total.labels(method=method, path=path, status=status).inc()
        request_duration_seconds.labels(method=method, path=path).observe(elapsed)

        return response


# ---------------------------------------------------------------------------
# /metrics endpoint handler (register in app.py)
# /metrics 端点处理器（在 app.py 中注册）
# ---------------------------------------------------------------------------


def metrics_endpoint() -> Response:
    """
    返回 Prometheus 文本格式指标数据（供 GET /metrics 端点使用）。
    Return Prometheus text-format metrics data (for GET /metrics endpoint).
    """
    data = generate_latest(METRICS_REGISTRY)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


