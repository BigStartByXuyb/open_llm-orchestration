"""
AppContainer 协调者 provider 配置测试（N-10）
Tests that AppContainer._get_coordinator_provider_id() respects COORDINATOR_PROVIDER setting.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from orchestration.shared.config import Settings
from orchestration.shared.enums import ProviderID
from orchestration.shared.errors import ConfigurationError


def _make_container_with_adapters(
    coordinator_provider: str,
    configured_providers: list[str] | None = None,
):
    """
    Build an AppContainer with mocked adapters for the specified providers.
    """
    from orchestration.wiring.container import AppContainer

    settings = Settings(
        JWT_SECRET_KEY="test-only-key",
        DATABASE_URL="postgresql+asyncpg://localhost/test",
        COORDINATOR_PROVIDER=coordinator_provider,
    )
    container = AppContainer(settings)

    # Build mock adapters for specified providers
    providers = configured_providers or ["anthropic", "openai"]
    container._adapters = {
        ProviderID(p): MagicMock() for p in providers
    }
    return container


class TestCoordinatorProviderConfig:
    def test_default_provider_is_anthropic(self) -> None:
        """Default COORDINATOR_PROVIDER should resolve to Anthropic."""
        container = _make_container_with_adapters("anthropic")
        pid = container._get_coordinator_provider_id()
        assert pid == ProviderID.ANTHROPIC

    def test_openai_coordinator_resolves_correctly(self) -> None:
        """Setting COORDINATOR_PROVIDER=openai should resolve to OpenAI adapter (N-10)."""
        container = _make_container_with_adapters("openai")
        pid = container._get_coordinator_provider_id()
        assert pid == ProviderID.OPENAI

    def test_deepseek_coordinator_resolves_correctly(self) -> None:
        """Setting COORDINATOR_PROVIDER=deepseek should resolve to DeepSeek."""
        container = _make_container_with_adapters(
            "deepseek", configured_providers=["deepseek", "anthropic"]
        )
        pid = container._get_coordinator_provider_id()
        assert pid == ProviderID.DEEPSEEK

    def test_unknown_provider_raises_configuration_error(self) -> None:
        """Unknown COORDINATOR_PROVIDER value must raise ConfigurationError (N-10)."""
        container = _make_container_with_adapters("anthropic")
        container._settings = Settings(
            JWT_SECRET_KEY="test-only-key",
            DATABASE_URL="postgresql+asyncpg://localhost/test",
            COORDINATOR_PROVIDER="completely_unknown_provider",
        )
        with pytest.raises(ConfigurationError):
            container._get_coordinator_provider_id()

    def test_unconfigured_provider_raises_configuration_error(self) -> None:
        """
        Valid ProviderID but no API key configured → ConfigurationError (N-10).
        E.g., COORDINATOR_PROVIDER=gemini but GEMINI adapter not in _adapters dict.
        """
        container = _make_container_with_adapters(
            "gemini", configured_providers=["anthropic", "openai"]
        )
        # gemini is a valid ProviderID but not in _adapters (no key configured)
        with pytest.raises(ConfigurationError, match="not configured"):
            container._get_coordinator_provider_id()
