"""
AppContainer 插件加载测试（N-02）
Tests that AppContainer._load_builtin_plugins() registers PromptPlugin skills.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from orchestration.plugins.loader import PluginLoader
from orchestration.plugins.registry import PluginRegistry


class TestContainerLoadsPromptPlugin:
    """
    N-02: _load_builtin_plugins() must register PromptPlugin and its skills.
    Verified by inspecting the PluginRegistry after calling the method.
    """

    def _build_minimal_container(self) -> tuple:
        """
        Build a minimal AppContainer with enough mocks to call _load_builtin_plugins().
        Returns (container, registry).
        """
        from orchestration.wiring.container import AppContainer
        from orchestration.shared.config import Settings

        settings = Settings(
            JWT_SECRET_KEY="test-only-key",
            DATABASE_URL="postgresql+asyncpg://localhost/test",
        )
        container = AppContainer(settings)

        # Wire up plugins_coord so _load_builtin_plugins() can run
        registry = PluginRegistry()
        loader = PluginLoader(registry)
        container._plugins_coord.registry = registry
        container._plugins_coord.loader = loader

        # Mock _load_iterative_skill to avoid needing adapters/transformers
        container._load_iterative_skill = MagicMock()  # type: ignore[method-assign]

        return container, registry

    def test_prompt_code_review_skill_registered(self) -> None:
        """After _load_builtin_plugins(), 'prompt_code_review' skill must be in registry."""
        container, registry = self._build_minimal_container()
        container._load_builtin_plugins()
        skill_ids = registry.list_skills()
        assert "prompt_code_review" in skill_ids, (
            f"Expected 'prompt_code_review' in skill_ids, got: {skill_ids}"
        )

    def test_prompt_plugin_itself_is_registered(self) -> None:
        """builtin_prompt_skills plugin must be registered after _load_builtin_plugins()."""
        container, registry = self._build_minimal_container()
        container._load_builtin_plugins()
        plugin_ids = registry.list_plugins()
        assert "builtin_prompt_skills" in plugin_ids, (
            f"Expected 'builtin_prompt_skills' in plugin_ids, got: {plugin_ids}"
        )

    def test_multiple_prompt_skills_registered(self) -> None:
        """At least 4 prompt skills must be registered (the built-in skill files)."""
        container, registry = self._build_minimal_container()
        container._load_builtin_plugins()
        prompt_skill_ids = [s for s in registry.list_skills() if s.startswith("prompt_")]
        assert len(prompt_skill_ids) >= 4, (
            f"Expected at least 4 prompt skills, got {len(prompt_skill_ids)}: {prompt_skill_ids}"
        )
