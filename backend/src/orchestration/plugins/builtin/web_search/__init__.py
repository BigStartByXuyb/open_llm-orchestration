"""
WebSearch 内置插件包
WebSearch built-in plugin package.
"""

from __future__ import annotations

from orchestration.shared.protocols import SkillProtocol
from orchestration.plugins.builtin.web_search.skill import WebSearchSkill


class WebSearchPlugin:
    """
    WebSearch 插件 — 将 WebSearchSkill 包装为 PluginProtocol
    WebSearch plugin — wraps WebSearchSkill as PluginProtocol.
    """

    plugin_id = "builtin_web_search"
    version = "1.0.0"

    def __init__(self, search_base_url: str = WebSearchSkill._DEFAULT_SEARCH_URL) -> None:
        self._skill = WebSearchSkill(search_base_url=search_base_url)
        self.skills: list[SkillProtocol] = [self._skill]  # type: ignore[list-item]

    def on_load(self) -> None:
        pass

    def on_unload(self) -> None:
        pass
