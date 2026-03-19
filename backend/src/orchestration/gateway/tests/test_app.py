"""
/metrics 端点单元测试（N-01）
Unit tests for /metrics endpoint (N-01 fix: Response import).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import Response

from orchestration.gateway.middleware.metrics import metrics_endpoint, CONTENT_TYPE_LATEST


def _make_metrics_app() -> FastAPI:
    """Minimal app with only the /metrics endpoint."""
    app = FastAPI()

    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics() -> Response:
        return metrics_endpoint()

    return app


class TestMetricsEndpoint:
    def test_metrics_returns_200(self) -> None:
        """GET /metrics must return HTTP 200."""
        app = _make_metrics_app()
        client = TestClient(app)
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_content_type_is_text_plain(self) -> None:
        """GET /metrics must return text/plain content type (Prometheus format)."""
        app = _make_metrics_app()
        client = TestClient(app)
        resp = client.get("/metrics")
        assert "text/plain" in resp.headers.get("content-type", "")

    def test_metrics_returns_response_instance(self) -> None:
        """metrics_endpoint() must return a Response (not JSONResponse)."""
        result = metrics_endpoint()
        assert isinstance(result, Response)
        assert result.media_type == CONTENT_TYPE_LATEST
