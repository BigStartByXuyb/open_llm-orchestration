"""
PluginRegistry 单元测试
Unit tests for PluginRegistry.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from orchestration.shared.types import RunContext
from orchestration.plugins.registry import PluginRegistry


# ---------------------------------------------------------------------------
# Helpers / 辅助工具
# ---------------------------------------------------------------------------

def make_skill(skill_id: str, description: str = "test skill") -> MagicMock:
    skill = MagicMock()
    skill.skill_id = skill_id
    skill.description = description
    skill.input_schema = {}
    skill.output_schema = {}
    return skill


def make_plugin(plugin_id: str, skill_ids: list[str] = (), version: str = "1.0") -> MagicMock:
    plugin = MagicMock()
    plugin.plugin_id = plugin_id
    plugin.version = version
    plugin.skills = [make_skill(sid) for sid in skill_ids]
    return plugin


# ---------------------------------------------------------------------------
# Tests / 测试
# ---------------------------------------------------------------------------

class TestRegisterAndLookup:
    def test_register_and_get_skill(self) -> None:
        registry = PluginRegistry()
        plugin = make_plugin("p1", ["skill_a", "skill_b"])
        registry.register_plugin(plugin)

        assert registry.get_skill("skill_a") is plugin.skills[0]
        assert registry.get_skill("skill_b") is plugin.skills[1]

    def test_list_skills(self) -> None:
        registry = PluginRegistry()
        registry.register_plugin(make_plugin("p1", ["z_skill", "a_skill"]))
        assert registry.list_skills() == ["a_skill", "z_skill"]  # sorted

    def test_list_plugins(self) -> None:
        registry = PluginRegistry()
        registry.register_plugin(make_plugin("p2"))
        registry.register_plugin(make_plugin("p1"))
        assert registry.list_plugins() == ["p1", "p2"]  # sorted

    def test_get_unknown_skill_raises_key_error(self) -> None:
        registry = PluginRegistry()
        with pytest.raises(KeyError, match="not found"):
            registry.get_skill("nonexistent")

    def test_get_plugin(self) -> None:
        registry = PluginRegistry()
        plugin = make_plugin("my_plugin")
        registry.register_plugin(plugin)
        assert registry.get_plugin("my_plugin") is plugin

    def test_get_unknown_plugin_raises_key_error(self) -> None:
        registry = PluginRegistry()
        with pytest.raises(KeyError):
            registry.get_plugin("nope")


class TestOverwrite:
    def test_re_register_same_skill_id_overwrites(self) -> None:
        """后注册的同名 Skill 应覆盖旧实例。"""
        registry = PluginRegistry()
        old_plugin = make_plugin("p1", ["shared_skill"])
        new_plugin = make_plugin("p2", ["shared_skill"])
        registry.register_plugin(old_plugin)
        registry.register_plugin(new_plugin)

        # 最新注册的覆盖 / Latest registration wins
        assert registry.get_skill("shared_skill") is new_plugin.skills[0]


class TestUnregister:
    def test_unregister_removes_plugin_and_skills(self) -> None:
        registry = PluginRegistry()
        plugin = make_plugin("p1", ["skill_x"])
        registry.register_plugin(plugin)
        registry.unregister_plugin("p1")

        assert "p1" not in registry.list_plugins()
        with pytest.raises(KeyError):
            registry.get_skill("skill_x")

    def test_unregister_nonexistent_is_noop(self) -> None:
        registry = PluginRegistry()
        registry.unregister_plugin("ghost")  # should not raise
