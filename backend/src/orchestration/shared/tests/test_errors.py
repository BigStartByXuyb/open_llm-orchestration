"""
shared/errors.py 单元测试
Unit tests for shared/errors.py — exception hierarchy and attributes.
"""

import pytest

from orchestration.shared.errors import (
    AuthError,
    ContextOverflowError,
    OrchestrationError,
    PluginError,
    ProviderError,
    ProviderUnavailable,
    RateLimitError,
    TenantIsolationError,
    TransformError,
)


class TestOrchestrationError:
    def test_basic(self) -> None:
        err = OrchestrationError("something went wrong")
        assert str(err) == "something went wrong"
        assert err.message == "something went wrong"
        assert err.code == ""

    def test_with_code(self) -> None:
        err = OrchestrationError("oops", code="ERR_001")
        assert err.code == "ERR_001"

    def test_repr(self) -> None:
        err = OrchestrationError("msg", code="X")
        assert "OrchestrationError" in repr(err)
        assert "msg" in repr(err)


class TestTransformError:
    def test_is_orchestration_error(self) -> None:
        err = TransformError("bad format")
        assert isinstance(err, OrchestrationError)

    def test_catchable_as_base(self) -> None:
        with pytest.raises(OrchestrationError):
            raise TransformError("format issue")


class TestProviderError:
    def test_attributes(self) -> None:
        err = ProviderError("http fail", status_code=500, provider_id="anthropic")
        assert err.status_code == 500
        assert err.provider_id == "anthropic"

    def test_is_orchestration_error(self) -> None:
        assert isinstance(ProviderError("x"), OrchestrationError)


class TestRateLimitError:
    def test_defaults(self) -> None:
        err = RateLimitError()
        assert err.status_code == 429
        assert err.code == "rate_limit"
        assert err.retry_after == 0.0

    def test_retry_after(self) -> None:
        err = RateLimitError("slow down", retry_after=30.5)
        assert err.retry_after == 30.5

    def test_is_provider_error(self) -> None:
        assert isinstance(RateLimitError(), ProviderError)


class TestAuthError:
    def test_defaults(self) -> None:
        err = AuthError()
        assert err.code == "auth_error"

    def test_is_provider_error(self) -> None:
        assert isinstance(AuthError(), ProviderError)


class TestProviderUnavailable:
    def test_defaults(self) -> None:
        err = ProviderUnavailable()
        assert err.code == "provider_unavailable"

    def test_is_provider_error(self) -> None:
        assert isinstance(ProviderUnavailable(), ProviderError)


class TestContextOverflowError:
    def test_attributes(self) -> None:
        err = ContextOverflowError(char_count=500_000, threshold=400_000)
        assert err.char_count == 500_000
        assert err.threshold == 400_000
        assert err.code == "context_overflow"

    def test_is_orchestration_error(self) -> None:
        assert isinstance(ContextOverflowError(), OrchestrationError)


class TestTenantIsolationError:
    def test_defaults(self) -> None:
        err = TenantIsolationError()
        assert err.code == "tenant_isolation"
        assert "isolation" in err.message.lower() or "tenant" in err.message.lower()

    def test_is_orchestration_error(self) -> None:
        assert isinstance(TenantIsolationError(), OrchestrationError)


class TestPluginError:
    def test_skill_id(self) -> None:
        err = PluginError("skill failed", skill_id="web_search")
        assert err.skill_id == "web_search"
        assert err.code == "plugin_error"

    def test_is_orchestration_error(self) -> None:
        assert isinstance(PluginError(), OrchestrationError)


class TestExceptionHierarchy:
    """验证完整异常层级结构 / Verify the complete exception hierarchy."""

    def test_catch_all_with_base(self) -> None:
        errors = [
            TransformError("t"),
            RateLimitError(),
            AuthError(),
            ProviderUnavailable(),
            ContextOverflowError(),
            TenantIsolationError(),
            PluginError(),
        ]
        for err in errors:
            assert isinstance(err, OrchestrationError), f"{type(err)} not OrchestrationError"

    def test_provider_errors_catchable_as_provider_error(self) -> None:
        for cls in [RateLimitError, AuthError, ProviderUnavailable]:
            assert isinstance(cls(), ProviderError)
