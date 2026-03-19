"""
Sprint 17: Executor 韧性测试 — 重试、熔断器、超时
Sprint 17: Executor resilience tests — retry, circuit breaker, timeout.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestration.orchestration.executor import CircuitBreaker, ParallelExecutor
from orchestration.shared.config import Settings
from orchestration.shared.enums import Capability, ProviderID, TaskStatus
from orchestration.shared.errors import ProviderError
from orchestration.shared.types import ProviderResult, RunContext, SubTask, TaskPlan


# ---------------------------------------------------------------------------
# Fixtures / 测试夹具
# ---------------------------------------------------------------------------


def _make_settings(**overrides) -> Settings:
    base = dict(
        JWT_SECRET_KEY="test-secret",
        DATABASE_URL="postgresql+asyncpg://localhost/test",
        REDIS_URL="redis://localhost:6379/0",
        PROVIDER_MAX_RETRIES=2,
        PROVIDER_RETRY_BASE_DELAY=0.0,  # zero delay for fast tests
        PROVIDER_TIMEOUT_SECONDS=5.0,
        CIRCUIT_BREAKER_FAILURE_THRESHOLD=3,
        CIRCUIT_BREAKER_RESET_TIMEOUT=30.0,
    )
    base.update(overrides)
    return Settings(**base)


def _make_context() -> RunContext:
    return RunContext(tenant_id="t1", session_id="s1", task_id="tk1")


def _make_llm_subtask(subtask_id: str = "st1") -> SubTask:
    return SubTask(
        subtask_id=subtask_id,
        description="test",
        provider_id=ProviderID.ANTHROPIC,
        capability=Capability.TEXT,
        context_slice=[],
        status=TaskStatus.PENDING,
    )


def _make_provider_result(subtask_id: str = "st1") -> ProviderResult:
    return ProviderResult(
        subtask_id=subtask_id,
        provider_id=ProviderID.ANTHROPIC,
        content="result",
        transformer_version="v3",
        tokens_used=100,
        latency_ms=50.0,
    )


# ---------------------------------------------------------------------------
# TestCircuitBreaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    """CircuitBreaker 状态机测试。"""

    def test_initial_state_is_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=30.0)
        assert cb.state == "closed"
        assert not cb.is_open()

    def test_failures_below_threshold_stay_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=30.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"

    def test_threshold_failures_open_circuit(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=30.0)
        for _ in range(3):
            cb.record_failure()
        assert cb.is_open()

    def test_success_resets_to_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=30.0)
        cb.record_failure()
        cb.record_success()
        assert cb.state == "closed"
        assert cb._failure_count == 0

    def test_success_after_threshold_resets(self) -> None:
        """After circuit opens, a success (e.g. in half-open) closes it."""
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=0.0)
        cb.record_failure()
        cb.record_failure()
        # transitions to half-open (reset_timeout=0)
        assert cb.state == "half-open"
        cb.record_success()
        assert cb.state == "closed"

    def test_open_transitions_to_half_open_after_timeout(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.0)
        cb.record_failure()
        # With reset_timeout=0, immediate transition
        assert cb.state == "half-open"

    def test_consecutive_success_resets_failure_count(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=30.0)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb._failure_count == 0


# ---------------------------------------------------------------------------
# TestRetryLogic
# ---------------------------------------------------------------------------


class TestRetryLogic:
    """_call_with_retry 重试逻辑测试。"""

    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt_no_retry(self) -> None:
        """No retry when first call succeeds."""
        settings = _make_settings(PROVIDER_MAX_RETRIES=2)
        executor = ParallelExecutor(
            transformer_registry=MagicMock(),
            adapters={},
            plugin_registry=MagicMock(),
            settings=settings,
        )

        call_count = 0

        async def coro():
            nonlocal call_count
            call_count += 1
            return _make_provider_result()

        result = await executor._call_with_retry("anthropic", coro)
        assert result.content == "result"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_provider_error_and_succeeds(self) -> None:
        """Retries when ProviderError, succeeds on second attempt."""
        settings = _make_settings(PROVIDER_MAX_RETRIES=2, PROVIDER_RETRY_BASE_DELAY=0.0)
        executor = ParallelExecutor(
            transformer_registry=MagicMock(),
            adapters={},
            plugin_registry=MagicMock(),
            settings=settings,
        )

        call_count = 0

        async def coro():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ProviderError("transient", code="transient", provider_id="anthropic")
            return _make_provider_result()

        result = await executor._call_with_retry("anthropic", coro)
        assert result.content == "result"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_raises_after_max_retries_exhausted(self) -> None:
        """Raises ProviderError after all retries exhausted."""
        settings = _make_settings(PROVIDER_MAX_RETRIES=2, PROVIDER_RETRY_BASE_DELAY=0.0)
        executor = ParallelExecutor(
            transformer_registry=MagicMock(),
            adapters={},
            plugin_registry=MagicMock(),
            settings=settings,
        )

        async def always_fail():
            raise ProviderError("persistent", code="error", provider_id="anthropic")

        with pytest.raises(ProviderError, match="persistent"):
            await executor._call_with_retry("anthropic", always_fail)

    @pytest.mark.asyncio
    async def test_timeout_raises_provider_error(self) -> None:
        """Provider call that exceeds timeout raises ProviderError with code='timeout'."""
        settings = _make_settings(
            PROVIDER_MAX_RETRIES=0,
            PROVIDER_TIMEOUT_SECONDS=0.01,  # 10ms timeout
        )
        executor = ParallelExecutor(
            transformer_registry=MagicMock(),
            adapters={},
            plugin_registry=MagicMock(),
            settings=settings,
        )

        async def slow_call():
            await asyncio.sleep(1.0)  # much longer than timeout
            return _make_provider_result()

        with pytest.raises(ProviderError) as exc_info:
            await executor._call_with_retry("anthropic", slow_call)
        assert exc_info.value.code == "timeout"

    @pytest.mark.asyncio
    async def test_circuit_open_raises_immediately(self) -> None:
        """When circuit is open, raises ProviderError without calling the function."""
        settings = _make_settings(
            PROVIDER_MAX_RETRIES=0,
            CIRCUIT_BREAKER_FAILURE_THRESHOLD=1,
            CIRCUIT_BREAKER_RESET_TIMEOUT=999.0,
        )
        executor = ParallelExecutor(
            transformer_registry=MagicMock(),
            adapters={},
            plugin_registry=MagicMock(),
            settings=settings,
        )
        # Manually open the circuit
        cb = executor._get_circuit_breaker("anthropic")
        cb.record_failure()
        assert cb.is_open()

        call_count = 0

        async def coro():
            nonlocal call_count
            call_count += 1
            return _make_provider_result()

        with pytest.raises(ProviderError) as exc_info:
            await executor._call_with_retry("anthropic", coro)
        assert exc_info.value.code == "circuit_open"
        assert call_count == 0  # function never called


# ---------------------------------------------------------------------------
# TestExecutorIntegrationWithRetry
# ---------------------------------------------------------------------------


class TestExecutorIntegrationWithRetry:
    """End-to-end executor tests verifying retry integrates with execute()."""

    @pytest.mark.asyncio
    async def test_single_provider_failure_retried_and_succeeds(self) -> None:
        """A single transient provider error is retried; task completes."""
        settings = _make_settings(PROVIDER_MAX_RETRIES=2, PROVIDER_RETRY_BASE_DELAY=0.0)

        call_count = 0

        async def flaky_call(raw_request, context):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ProviderError("transient", code="transient", provider_id="anthropic")
            return {"content": "ok", "tokens": 50, "model": "claude-3", "raw": {}}

        mock_transformer = MagicMock()
        mock_transformer.transform.return_value = {}
        mock_transformer.parse_response.return_value = _make_provider_result()

        mock_transformer_registry = MagicMock()
        mock_transformer_registry.get.return_value = mock_transformer

        mock_adapter = MagicMock()
        mock_adapter.call = AsyncMock(side_effect=flaky_call)

        executor = ParallelExecutor(
            transformer_registry=mock_transformer_registry,
            adapters={ProviderID.ANTHROPIC: mock_adapter},
            plugin_registry=MagicMock(),
            settings=settings,
        )

        subtask = _make_llm_subtask()
        plan = TaskPlan("plan1", subtasks=[subtask])
        ctx = _make_context()

        results = await executor.execute(plan, ctx)
        assert len(results) == 1
        assert call_count == 2  # 1 failure + 1 success


# ---------------------------------------------------------------------------
# TestReadyzDetailedResponse
# ---------------------------------------------------------------------------


class TestReadyzDetailedResponse:
    """Sprint 17: /readyz must return per-component status detail."""

    def test_readyz_ok_response_has_components(self) -> None:
        """When DB + Redis are healthy, /readyz returns components dict."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from fastapi.testclient import TestClient
        from orchestration.gateway.app import create_app
        from orchestration.shared.config import Settings

        test_settings = Settings(
            JWT_SECRET_KEY="test-secret",
            DATABASE_URL="postgresql+asyncpg://localhost/test",
            REDIS_URL="redis://localhost:6379/0",
        )

        app = create_app(test_settings)

        mock_container = MagicMock()
        mock_container.settings = test_settings

        # Mock healthy DB session
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=None)
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_container.db_session_factory = MagicMock(return_value=mock_session_ctx)

        # Mock healthy Redis
        mock_container.redis = AsyncMock()
        mock_container.redis.ping = AsyncMock(return_value=True)

        app.state.container = mock_container

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/readyz")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "components" in body
        assert body["components"]["db"] == "ok"
        assert body["components"]["redis"] == "ok"

    def test_readyz_503_when_db_down(self) -> None:
        """When DB is unavailable, /readyz returns 503 with error detail."""
        from unittest.mock import AsyncMock, MagicMock
        from fastapi.testclient import TestClient
        from orchestration.gateway.app import create_app
        from orchestration.shared.config import Settings

        test_settings = Settings(
            JWT_SECRET_KEY="test-secret",
            DATABASE_URL="postgresql+asyncpg://localhost/test",
            REDIS_URL="redis://localhost:6379/0",
        )

        app = create_app(test_settings)

        mock_container = MagicMock()
        mock_container.settings = test_settings

        # Mock failing DB
        mock_session_ctx = AsyncMock()
        mock_session_ctx.__aenter__ = AsyncMock(
            side_effect=Exception("Connection refused")
        )
        mock_session_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_container.db_session_factory = MagicMock(return_value=mock_session_ctx)

        # Mock healthy Redis
        mock_container.redis = AsyncMock()
        mock_container.redis.ping = AsyncMock(return_value=True)

        app.state.container = mock_container

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/readyz")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "unavailable"
        assert "db" in body["components"]
        assert "error:" in body["components"]["db"]
