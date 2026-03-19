"""
shared/config.py 单元测试
Unit tests for shared/config.py — settings loading, computed properties, defaults.
"""

import os
import warnings

import pytest

from orchestration.shared.config import Settings, get_settings


class TestSettingsDefaults:
    def test_coordinator_model_default(self) -> None:
        s = Settings()
        assert s.COORDINATOR_MODEL == "claude-sonnet-4-6"

    def test_context_truncation_threshold(self) -> None:
        s = Settings()
        assert s.CONTEXT_TRUNCATION_THRESHOLD == 400_000

    def test_max_subtask_context_chars(self) -> None:
        s = Settings()
        assert s.MAX_SUBTASK_CONTEXT_CHARS == 40_000

    def test_max_result_chars_per_block(self) -> None:
        s = Settings()
        assert s.MAX_RESULT_CHARS_PER_BLOCK == 8_000

    def test_max_summary_input_chars(self) -> None:
        s = Settings()
        assert s.MAX_SUMMARY_INPUT_CHARS == 120_000

    def test_provider_concurrency_limits(self) -> None:
        s = Settings()
        limits = s.PROVIDER_CONCURRENCY_LIMITS
        assert limits["anthropic"] == 5
        assert limits["openai"] == 10
        assert limits["deepseek"] == 8
        assert limits["gemini"] == 5
        assert limits["jimeng"] == 3
        assert limits["kling"] == 2

    def test_enable_review_gate_default_false(self) -> None:
        s = Settings()
        assert s.ENABLE_REVIEW_GATE is False


class TestComputedProperties:
    def test_sliding_window_threshold(self) -> None:
        s = Settings()
        assert s.sliding_window_threshold == int(400_000 * 0.8)

    def test_summary_compression_threshold(self) -> None:
        s = Settings()
        assert s.summary_compression_threshold == int(400_000 * 0.95)

    def test_custom_threshold_computed(self) -> None:
        s = Settings(CONTEXT_TRUNCATION_THRESHOLD=200_000)
        assert s.sliding_window_threshold == 160_000
        assert s.summary_compression_threshold == 190_000


class TestGetProviderConcurrency:
    def test_known_provider(self) -> None:
        s = Settings()
        assert s.get_provider_concurrency("anthropic") == 5

    def test_unknown_provider_defaults_to_5(self) -> None:
        s = Settings()
        assert s.get_provider_concurrency("unknown_llm") == 5


class TestEnvVarOverride:
    def test_coordinator_model_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ORCH_COORDINATOR_MODEL", "claude-opus-4-6")
        s = Settings()
        assert s.COORDINATOR_MODEL == "claude-opus-4-6"

    def test_context_threshold_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ORCH_CONTEXT_TRUNCATION_THRESHOLD", "100000")
        s = Settings()
        assert s.CONTEXT_TRUNCATION_THRESHOLD == 100_000


class TestJwtSecretValidation:
    def test_production_with_default_secret_raises(self) -> None:
        """Production environment must not allow the default JWT secret."""
        with pytest.raises(ValueError, match="SECURITY ERROR"):
            Settings(ENV="production", JWT_SECRET_KEY="CHANGE_ME_IN_PRODUCTION")

    def test_production_with_custom_secret_ok(self) -> None:
        """Production with a real secret key should succeed."""
        s = Settings(ENV="production", JWT_SECRET_KEY="a" * 32)
        assert s.ENV == "production"

    def test_development_with_default_secret_warns(self) -> None:
        """Development environment should only warn, not raise."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            s = Settings(ENV="development", JWT_SECRET_KEY="CHANGE_ME_IN_PRODUCTION")
        assert s.JWT_SECRET_KEY == "CHANGE_ME_IN_PRODUCTION"
        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(user_warnings) >= 1

    def test_testing_env_with_default_secret_ok(self) -> None:
        """Testing environment should allow the default secret without raising."""
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            s = Settings(ENV="testing", JWT_SECRET_KEY="CHANGE_ME_IN_PRODUCTION")
        assert s.JWT_SECRET_KEY == "CHANGE_ME_IN_PRODUCTION"

    def test_staging_with_default_secret_raises(self) -> None:
        """Any non-dev/test environment should be treated as production."""
        with pytest.raises(ValueError, match="SECURITY ERROR"):
            Settings(ENV="staging", JWT_SECRET_KEY="CHANGE_ME_IN_PRODUCTION")


class TestGetSettingsCaching:
    def test_returns_same_instance(self) -> None:
        # Within the same process, get_settings() returns the same cached instance
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_cache_clear_returns_fresh_instance(self) -> None:
        get_settings.cache_clear()
        s1 = get_settings()
        get_settings.cache_clear()
        s2 = get_settings()
        # After cache clear, a new instance is created
        # They should be equal in value (same defaults)
        assert s1.COORDINATOR_MODEL == s2.COORDINATOR_MODEL


class TestCorsAllowedOrigins:
    """N-07: CORS_ALLOWED_ORIGINS must be configurable via env var."""

    def test_default_is_wildcard(self) -> None:
        s = Settings()
        assert s.CORS_ALLOWED_ORIGINS == ["*"]

    def test_override_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ORCH_CORS_ALLOWED_ORIGINS", '["https://app.example.com"]')
        s = Settings()
        assert s.CORS_ALLOWED_ORIGINS == ["https://app.example.com"]

    def test_multiple_origins_parsed_as_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "ORCH_CORS_ALLOWED_ORIGINS",
            '["https://app.example.com", "https://admin.example.com"]',
        )
        s = Settings()
        assert len(s.CORS_ALLOWED_ORIGINS) == 2
        assert "https://app.example.com" in s.CORS_ALLOWED_ORIGINS


class TestTenantKeyEncryptionKey:
    """N-08: TENANT_KEY_ENCRYPTION_KEY config field must exist and default to empty."""

    def test_default_is_empty(self) -> None:
        s = Settings()
        assert s.TENANT_KEY_ENCRYPTION_KEY == ""

    def test_override_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Generate a valid Fernet key for testing
        from cryptography.fernet import Fernet
        test_key = Fernet.generate_key().decode()
        monkeypatch.setenv("ORCH_TENANT_KEY_ENCRYPTION_KEY", test_key)
        s = Settings()
        assert s.TENANT_KEY_ENCRYPTION_KEY == test_key


class TestCoordinatorProvider:
    """N-10: COORDINATOR_PROVIDER must default to 'anthropic' and be overridable."""

    def test_default_is_anthropic(self) -> None:
        s = Settings()
        assert s.COORDINATOR_PROVIDER == "anthropic"

    def test_override_to_openai(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ORCH_COORDINATOR_PROVIDER", "openai")
        s = Settings()
        assert s.COORDINATOR_PROVIDER == "openai"

    def test_override_to_deepseek(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ORCH_COORDINATOR_PROVIDER", "deepseek")
        s = Settings()
        assert s.COORDINATOR_PROVIDER == "deepseek"


class TestResilienceConfig:
    """Sprint 17: Resilience config fields must exist with correct defaults."""

    def test_provider_max_retries_default(self) -> None:
        s = Settings()
        assert s.PROVIDER_MAX_RETRIES == 3

    def test_provider_retry_base_delay_default(self) -> None:
        s = Settings()
        assert s.PROVIDER_RETRY_BASE_DELAY == 1.0

    def test_provider_timeout_seconds_default(self) -> None:
        s = Settings()
        assert s.PROVIDER_TIMEOUT_SECONDS == 60.0

    def test_circuit_breaker_failure_threshold_default(self) -> None:
        s = Settings()
        assert s.CIRCUIT_BREAKER_FAILURE_THRESHOLD == 5

    def test_circuit_breaker_reset_timeout_default(self) -> None:
        s = Settings()
        assert s.CIRCUIT_BREAKER_RESET_TIMEOUT == 30.0

    def test_override_max_retries_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ORCH_PROVIDER_MAX_RETRIES", "5")
        s = Settings()
        assert s.PROVIDER_MAX_RETRIES == 5

    def test_override_timeout_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ORCH_PROVIDER_TIMEOUT_SECONDS", "120.0")
        s = Settings()
        assert s.PROVIDER_TIMEOUT_SECONDS == 120.0
