"""
TransformerRegistry 单元测试
Unit tests for TransformerRegistry — versioned lookup and registration.
"""

import pytest

from orchestration.shared.enums import ProviderID
from orchestration.transformer.registry import TransformerRegistry
from orchestration.transformer.providers.anthropic_v3.transformer import AnthropicV3Transformer
from orchestration.transformer.providers.openai_v1.transformer import OpenAIV1Transformer


@pytest.fixture()
def registry() -> TransformerRegistry:
    return TransformerRegistry()


@pytest.fixture()
def populated_registry() -> TransformerRegistry:
    reg = TransformerRegistry()
    reg.register(AnthropicV3Transformer())
    reg.register(OpenAIV1Transformer())
    return reg


class TestRegister:
    def test_register_and_get(self, registry: TransformerRegistry) -> None:
        tr = AnthropicV3Transformer()
        registry.register(tr)
        result = registry.get(ProviderID.ANTHROPIC, "v3")
        assert result is tr

    def test_duplicate_registration_overwrites(self, registry: TransformerRegistry) -> None:
        tr1 = AnthropicV3Transformer(model="claude-sonnet-4-6")
        tr2 = AnthropicV3Transformer(model="claude-opus-4-6")
        registry.register(tr1)
        registry.register(tr2)
        result = registry.get(ProviderID.ANTHROPIC, "v3")
        assert result is tr2  # Latest overwrites

    def test_len_increases(self, registry: TransformerRegistry) -> None:
        assert len(registry) == 0
        registry.register(AnthropicV3Transformer())
        assert len(registry) == 1
        registry.register(OpenAIV1Transformer())
        assert len(registry) == 2


class TestGet:
    def test_not_found_raises_key_error(self, registry: TransformerRegistry) -> None:
        with pytest.raises(KeyError, match="No transformer registered"):
            registry.get(ProviderID.ANTHROPIC, "v99")

    def test_error_message_includes_registered(
        self, populated_registry: TransformerRegistry
    ) -> None:
        with pytest.raises(KeyError) as exc_info:
            populated_registry.get(ProviderID.DEEPSEEK, "v1")
        assert "anthropic" in str(exc_info.value).lower() or "openai" in str(exc_info.value).lower()


class TestListVersions:
    def test_versions_for_known_provider(
        self, populated_registry: TransformerRegistry
    ) -> None:
        versions = populated_registry.list_versions(ProviderID.ANTHROPIC)
        assert "v3" in versions

    def test_versions_for_unknown_provider_empty(
        self, populated_registry: TransformerRegistry
    ) -> None:
        versions = populated_registry.list_versions(ProviderID.DEEPSEEK)
        assert versions == []

    def test_versions_sorted(self, registry: TransformerRegistry) -> None:
        # Register two versions by patching
        from orchestration.transformer.providers.anthropic_v3.transformer import AnthropicV3Transformer as A
        class AnthropicV4(A):
            api_version = "v4"
        registry.register(AnthropicV3Transformer())
        registry.register(AnthropicV4())
        versions = registry.list_versions(ProviderID.ANTHROPIC)
        assert versions == sorted(versions)


class TestListAll:
    def test_list_all(self, populated_registry: TransformerRegistry) -> None:
        all_entries = populated_registry.list_all()
        assert (ProviderID.ANTHROPIC, "v3") in all_entries
        assert (ProviderID.OPENAI, "v1") in all_entries

    def test_empty_registry(self, registry: TransformerRegistry) -> None:
        assert registry.list_all() == []


class TestRepr:
    def test_repr_shows_entries(self, populated_registry: TransformerRegistry) -> None:
        r = repr(populated_registry)
        assert "TransformerRegistry" in r
