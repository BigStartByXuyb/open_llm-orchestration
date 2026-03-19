"""
MCPPlugin — 将 MCP 服务器包装为 PluginProtocol
MCPPlugin — Wraps an MCP server as PluginProtocol.

Layer 4: Only imports from shared/ and mcp/.

生命周期 / Lifecycle:
  1. wiring/container.py 调用 MCPClient.connect() 并 list_tools()
     wiring/container.py calls MCPClient.connect() and list_tools()
  2. 构建 MCPSkill 列表，创建 MCPPlugin 实例
     Build MCPSkill list, create MCPPlugin instance
  3. PluginLoader.load_plugin_instance(mcp_plugin) 调用 on_load()，注册到 PluginRegistry
     PluginLoader.load_plugin_instance(mcp_plugin) calls on_load(), registers to PluginRegistry
  4. 关闭时：调用 mcp_plugin.aclose() 断开连接（on_unload 为同步轻量钩子）
     On shutdown: call mcp_plugin.aclose() to disconnect (on_unload is a lightweight sync hook)
"""

from __future__ import annotations

import logging

from orchestration.shared.protocols import SkillProtocol
from orchestration.mcp.client import MCPClient
from orchestration.mcp.skill_adapter import MCPSkill

logger = logging.getLogger(__name__)


class MCPPlugin:
    """
    MCP 服务器适配器 — 实现 PluginProtocol
    MCP server adapter — implements PluginProtocol.
    """

    def __init__(
        self,
        server_id: str,
        client: MCPClient,
        skills: list[MCPSkill],
        version: str = "1.0.0",
    ) -> None:
        self.plugin_id = f"mcp::{server_id}"
        self.version = version
        self._client = client
        self._skills = skills
        self._loaded = False

    @property
    def skills(self) -> list[SkillProtocol]:
        """返回 MCPSkill 列表（实现 SkillProtocol）/ Return MCPSkill list (implementing SkillProtocol)."""
        return self._skills  # type: ignore[return-value]

    def on_load(self) -> None:
        """
        插件加载钩子（同步，轻量）— 连接已由 wiring 层建立
        Plugin load hook (sync, lightweight) — connection already established by wiring layer.
        """
        self._loaded = True
        logger.info(
            "MCPPlugin '%s' loaded with %d tool(s): %s",
            self.plugin_id,
            len(self._skills),
            [s.skill_id for s in self._skills],
        )

    def on_unload(self) -> None:
        """
        插件卸载钩子（同步，轻量）— 实际断连由 aclose() 负责
        Plugin unload hook (sync, lightweight) — actual disconnect handled by aclose().
        """
        self._loaded = False
        logger.info("MCPPlugin '%s' unloaded (call aclose() for async cleanup)", self.plugin_id)

    async def aclose(self) -> None:
        """
        异步关闭：断开 MCP 连接
        Async close: disconnect from MCP server.
        Called by wiring/container.py during shutdown, NOT by PluginProtocol.on_unload().
        """
        await self._client.close()
        logger.info("MCPPlugin '%s' connection closed", self.plugin_id)
