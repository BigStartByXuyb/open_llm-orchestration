"""
BrowserPlugin — 浏览器自动化插件（包装 BrowserSkill）
BrowserPlugin — Browser automation plugin (wraps BrowserSkill).

Layer 4: Only imports from within browser/ and shared/.
"""

from __future__ import annotations

import logging

from orchestration.plugins.builtin.browser.skill import BrowserSkill

logger = logging.getLogger(__name__)


class BrowserPlugin:
    """
    浏览器自动化插件 — 实现 PluginProtocol，包装 BrowserSkill
    Browser automation plugin — implements PluginProtocol, wraps BrowserSkill.
    """

    plugin_id = "builtin_browser"
    version = "1.0.0"

    def __init__(self) -> None:
        self._skill = BrowserSkill()
        self.skills = [self._skill]

    def on_load(self) -> None:
        logger.info("BrowserPlugin loaded — skill_id=%s", self._skill.skill_id)

    def on_unload(self) -> None:
        logger.info("BrowserPlugin unloaded")
