"""
Prometheus 指标中间件单元测试
Unit tests for Prometheus metrics middleware.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest


def _make_isolated_registry() -> CollectorRegistry:
    """Each test gets its own registry to avoid metric name collision."""
    return CollectorRegistry()


def _make_app(registry: CollectorRegistry) -> FastAPI:
    """Minimal app with MetricsMiddleware wired to an isolated registry."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response
    import time
    import re

    req_counter = Counter(
        "test_requests_total", "total", ["method", "path", "status"], registry=registry
    )
    duration_hist = Histogram(
        "test_request_duration_seconds", "duration", ["method", "path"], registry=registry
    )

    app = FastAPI()

    class _TestMetricsMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: object) -> Response:
            start = time.monotonic()
            response = await call_next(request)  # type: ignore[call-arg]
            elapsed = time.monotonic() - start
            path = request.url.path
            status = str(response.status_code)
            req_counter.labels(method=request.method, path=path, status=status).inc()
            duration_hist.labels(method=request.method, path=path).observe(elapsed)
            return response

    app.add_middleware(_TestMetricsMiddleware)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"pong": "ok"}

    @app.get("/metrics")
    async def metrics_ep() -> Response:
        data = generate_latest(registry)
        return Response(content=data, media_type="text/plain; version=0.0.4; charset=utf-8")

    return app


class TestNormalizePath:
    def test_uuid_replaced(self) -> None:
        from orchestration.gateway.middleware.metrics import _normalize_path
        result = _normalize_path("/tasks/abc12345-1234-1234-1234-abcdefabcdef")
        assert "{id}" in result
        assert "abc12345" not in result

    def test_numeric_id_replaced(self) -> None:
        from orchestration.gateway.middleware.metrics import _normalize_path
        result = _normalize_path("/sessions/42")
        assert "{id}" in result

    def test_static_path_unchanged(self) -> None:
        from orchestration.gateway.middleware.metrics import _normalize_path
        assert _normalize_path("/health") == "/health"
        assert _normalize_path("/metrics") == "/metrics"

    def test_nested_uuid_replaced(self) -> None:
        from orchestration.gateway.middleware.metrics import _normalize_path
        path = "/tenants/550e8400-e29b-41d4-a716-446655440000/keys"
        result = _normalize_path(path)
        assert "{id}" in result
        assert "550e8400" not in result


class TestMetricsMiddleware:
    def test_requests_total_increments(self) -> None:
        registry = _make_isolated_registry()
        app = _make_app(registry)
        client = TestClient(app)
        client.get("/ping")
        output = generate_latest(registry).decode()
        assert "test_requests_total" in output
        assert 'status="200"' in output

    def test_duration_histogram_populated(self) -> None:
        registry = _make_isolated_registry()
        app = _make_app(registry)
        client = TestClient(app)
        client.get("/ping")
        output = generate_latest(registry).decode()
        assert "test_request_duration_seconds" in output

    def test_metrics_endpoint_returns_prometheus_format(self) -> None:
        registry = _make_isolated_registry()
        app = _make_app(registry)
        client = TestClient(app)
        # Hit an endpoint to populate a metric
        client.get("/ping")
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")
        assert "test_requests_total" in resp.text


class TestPrometheusHelpers:
    def test_record_provider_call(self) -> None:
        from orchestration.gateway.middleware.metrics import (
            record_provider_call,
            provider_calls_total,
        )
        # Use the global metric; just verify it doesn't raise
        before = provider_calls_total.labels(provider_id="test_prov")._value.get()
        record_provider_call("test_prov")
        after = provider_calls_total.labels(provider_id="test_prov")._value.get()
        assert after == before + 1

    def test_active_tasks_gauge_inc_dec(self) -> None:
        from orchestration.gateway.middleware.metrics import active_tasks_gauge
        before = active_tasks_gauge._value.get()
        active_tasks_gauge.inc()
        assert active_tasks_gauge._value.get() == before + 1
        active_tasks_gauge.dec()
        assert active_tasks_gauge._value.get() == before


class TestSubtaskMetrics:
    """N-14: Subtask-level Prometheus metrics (subtask_total, subtask_duration_seconds)."""

    def test_subtask_total_counter_exists(self) -> None:
        """subtask_total counter must be importable and incrementable."""
        from orchestration.gateway.middleware.metrics import subtask_total
        before = subtask_total.labels(capability="text", status="success")._value.get()
        subtask_total.labels(capability="text", status="success").inc()
        after = subtask_total.labels(capability="text", status="success")._value.get()
        assert after == before + 1

    def test_subtask_duration_histogram_exists(self) -> None:
        """subtask_duration_seconds histogram must be importable and observable."""
        from orchestration.gateway.middleware.metrics import subtask_duration_seconds
        # Observing should not raise
        subtask_duration_seconds.labels(capability="text", provider="anthropic").observe(0.5)

    def test_tool_turns_total_counter_exists(self) -> None:
        """tool_turns_total counter must be importable and incrementable."""
        from orchestration.gateway.middleware.metrics import tool_turns_total
        before = tool_turns_total.labels(skill_id="web_search")._value.get()
        tool_turns_total.labels(skill_id="web_search").inc()
        after = tool_turns_total.labels(skill_id="web_search")._value.get()
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_executor_records_subtask_total_on_skill_execution(self) -> None:
        """
        N-14: After executing a skill subtask, subtask_total counter must increment.
        Uses the global registry — just checks no exception is raised and counter increments.
        """
        from unittest.mock import AsyncMock, MagicMock
        from orchestration.orchestration.executor import ParallelExecutor
        from orchestration.shared.enums import ProviderID, Capability, TaskStatus
        from orchestration.shared.types import SubTask, TaskPlan, RunContext
        from orchestration.gateway.middleware.metrics import subtask_total

        before = subtask_total.labels(capability="text", status="success")._value.get()

        skill = AsyncMock()
        skill.execute = AsyncMock(return_value={"result": "done"})

        plugin_registry = MagicMock()
        plugin_registry.get_skill = MagicMock(return_value=skill)

        executor = ParallelExecutor(
            transformer_registry=MagicMock(),
            adapters={},
            plugin_registry=plugin_registry,
        )

        subtask = SubTask(
            subtask_id="st_metrics",
            description="test metrics",
            provider_id=ProviderID.SKILL,
            capability=Capability.TEXT,
            skill_id="test_skill",
            context_slice=[],
            status=TaskStatus.PENDING,
        )
        plan = TaskPlan("p1", subtasks=[subtask])
        ctx = RunContext(tenant_id="t1", session_id="s1", task_id="tk1")

        await executor.execute(plan, ctx)

        after = subtask_total.labels(capability="text", status="success")._value.get()
        assert after == before + 1
