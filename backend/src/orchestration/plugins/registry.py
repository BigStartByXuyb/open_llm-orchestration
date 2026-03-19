"""
PluginRegistry — 插件和 Skill 注册表
PluginRegistry — Plugin and Skill registry.

Layer 4: Only imports from shared/.

实现 shared/protocols.py 中的 PluginRegistryProtocol。
Implements PluginRegistryProtocol from shared/protocols.py.
"""

from __future__ import annotations

from orchestration.shared.errors import PluginError
from orchestration.shared.protocols import PluginProtocol, SkillProtocol


class PluginRegistry:
    """
    插件注册表 — 管理所有已加载插件及其 Skill。
    Plugin registry — manages all loaded plugins and their skills.

    Skill ID 必须在全局唯一；重复注册同名 Skill 会覆盖旧实例（后注册优先）。
    Skill IDs must be globally unique; re-registering the same skill_id overwrites the old one.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, PluginProtocol] = {}
        self._skills: dict[str, SkillProtocol] = {}

    def register_plugin(self, plugin: PluginProtocol) -> None:
        """
        注册插件及其所有 Skill
        Register a plugin and all its skills.
        """
        self._plugins[plugin.plugin_id] = plugin
        for skill in plugin.skills:
            self._skills[skill.skill_id] = skill

    def get_skill(self, skill_id: str) -> SkillProtocol:
        """
        按 skill_id 查找 Skill；未找到抛 KeyError。
        Look up skill by skill_id; raises KeyError if not found.
        """
        if skill_id not in self._skills:
            raise KeyError(f"Skill '{skill_id}' not found in registry")
        return self._skills[skill_id]

    def list_skills(self) -> list[str]:
        """列出所有已注册 Skill 的 ID / List all registered skill IDs."""
        return sorted(self._skills.keys())

    def list_plugins(self) -> list[str]:
        """列出所有已注册插件的 ID / List all registered plugin IDs."""
        return sorted(self._plugins.keys())

    def get_plugin(self, plugin_id: str) -> PluginProtocol:
        """按 plugin_id 查找插件 / Look up plugin by plugin_id."""
        if plugin_id not in self._plugins:
            raise KeyError(f"Plugin '{plugin_id}' not found in registry")
        return self._plugins[plugin_id]

    def unregister_plugin(self, plugin_id: str) -> None:
        """
        注销插件及其所有 Skill（不调用 on_unload，由调用方负责）
        Unregister plugin and all its skills (does NOT call on_unload — caller's responsibility).
        """
        plugin = self._plugins.pop(plugin_id, None)
        if plugin is None:
            return
        for skill in plugin.skills:
            self._skills.pop(skill.skill_id, None)
