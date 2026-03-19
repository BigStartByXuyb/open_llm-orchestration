"""
TracingMiddleware 单元测试
TracingMiddleware unit tests.

测试覆盖 / Test coverage:
  - trace_id 注入到 request.state / trace_id injected into request.state
  - x-trace-id 出现在响应头 / x-trace-id present in response header
  - 不同请求获得不同 trace_id / different requests get different trace_ids
  - W3C traceparent 头被解析 / W3C traceparent header is parsed
  - /health 路径不注入追踪 / /health path skips tracing
  - _parse_traceparent 解析逻辑 / _parse_traceparent parsing logic
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from orchestration.gateway.middleware.tracing import TracingMiddleware, _parse_traceparent


# ---------------------------------------------------------------------------
# Fixtures / 固定装置
# ---------------------------------------------------------------------------


@pytest.fixture()
def tracing_app() -> FastAPI:
    """Simple FastAPI app with only TracingMiddleware attached."""
    app = FastAPI()
    app.add_middleware(TracingMiddleware)

    @app.get("/test")
    async def test_endpoint(request: Request) -> dict[str, str]:
        return {"trace_id": getattr(request.state, "trace_id", "")}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


@pytest.fixture()
def client(tracing_app: FastAPI) -> TestClient:
    return TestClient(tracing_app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Tests: middleware behaviour / 中间件行为测试
# ---------------------------------------------------------------------------


class TestTracingMiddleware:
    def test_x_trace_id_in_response_header(self, client: TestClient) -> None:
        """x-trace-id should appear in every non-skipped response."""
        resp = client.get("/test")
        assert resp.status_code == 200
        assert "x-trace-id" in resp.headers

    def test_trace_id_is_32_hex_chars(self, client: TestClient) -> None:
        """trace_id should be a 32-char lowercase hex string (128-bit)."""
        resp = client.get("/test")
        trace_id = resp.headers["x-trace-id"]
        assert len(trace_id) == 32
        int(trace_id, 16)  # raises ValueError if not valid hex

    def test_trace_id_injected_in_request_state(self, client: TestClient) -> None:
        """request.state.trace_id must match the x-trace-id header."""
        resp = client.get("/test")
        body = resp.json()
        assert body["trace_id"] == resp.headers["x-trace-id"]

    def test_different_requests_get_unique_trace_ids(self, client: TestClient) -> None:
        """Each request should receive a distinct trace_id."""
        id1 = client.get("/test").headers["x-trace-id"]
        id2 = client.get("/test").headers["x-trace-id"]
        assert id1 != id2

    def test_health_endpoint_skips_tracing(self, client: TestClient) -> None:
        """Requests to /health must NOT receive x-trace-id in response."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert "x-trace-id" not in resp.headers

    def test_valid_traceparent_header_is_respected(self, client: TestClient) -> None:
        """Valid W3C traceparent header → trace_id should match its trace-id field."""
        # Format: version-trace_id-parent_id-flags
        expected_trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
        traceparent = f"00-{expected_trace_id}-00f067aa0ba902b7-01"
        resp = client.get("/test", headers={"traceparent": traceparent})
        assert resp.status_code == 200
        assert resp.headers["x-trace-id"] == expected_trace_id

    def test_invalid_traceparent_falls_back_to_generated_id(
        self, client: TestClient
    ) -> None:
        """Invalid traceparent header → middleware generates its own trace_id."""
        resp = client.get("/test", headers={"traceparent": "not-valid"})
        assert resp.status_code == 200
        trace_id = resp.headers["x-trace-id"]
        assert len(trace_id) == 32  # generated, not from header


# ---------------------------------------------------------------------------
# Tests: _parse_traceparent helper / 辅助函数测试
# ---------------------------------------------------------------------------


class TestParseTraceparent:
    def test_valid_traceparent(self) -> None:
        result = _parse_traceparent(
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        )
        assert result == "4bf92f3577b34da6a3ce929d0e0e4736"

    def test_uppercase_trace_id_normalized(self) -> None:
        result = _parse_traceparent(
            "00-4BF92F3577B34DA6A3CE929D0E0E4736-00f067aa0ba902b7-01"
        )
        assert result == "4bf92f3577b34da6a3ce929d0e0e4736"

    def test_wrong_version_returns_none(self) -> None:
        # Version must be "00"
        result = _parse_traceparent(
            "ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        )
        assert result is None

    def test_wrong_trace_id_length_returns_none(self) -> None:
        result = _parse_traceparent("00-tooshort-00f067aa0ba902b7-01")
        assert result is None

    def test_non_hex_trace_id_returns_none(self) -> None:
        result = _parse_traceparent(
            "00-zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz-00f067aa0ba902b7-01"
        )
        assert result is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_traceparent("") is None

    def test_wrong_number_of_parts_returns_none(self) -> None:
        assert _parse_traceparent("00-abc-01") is None
        assert _parse_traceparent("00-abc-def-ghi-extra") is None
