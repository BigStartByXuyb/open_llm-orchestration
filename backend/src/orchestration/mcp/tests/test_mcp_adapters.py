"""
MCP 适配器单元测试（Mock MCPClient，无需真实 MCP 服务器）
Unit tests for MCP adapters (Mock MCPClient, no real MCP server needed).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestration.shared.errors import PluginError
from orchestration.shared.types import RunContext
from orchestration.mcp.client import MCPClient, MCPServerConfig
from orchestration.mcp.skill_adapter import MCPSkill
from orchestration.mcp.plugin_adapter import MCPPlugin
from orchestration.mcp.registry import MCPRegistry


# ---------------------------------------------------------------------------
# Helpers / 辅助
# ---------------------------------------------------------------------------

@pytest.fixture()
def ctx() -> RunContext:
    return RunContext(tenant_id="t1", session_id="s1", task_id="tk1")


def make_mcp_tool(name: str, description: str = "test tool") -> MagicMock:
    """创建一个 Mock MCP Tool / Create a mock MCP Tool."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = {"type": "object", "properties": {"query": {"type": "string"}}}
    return tool


def make_mock_client(server_id: str = "test_server", connected: bool = True) -> AsyncMock:
    """创建一个 Mock MCPClient / Create a mock MCPClient."""
    client = AsyncMock(spec=MCPClient)
    client.server_id = server_id
    client.is_connected = connected
    return client


# ---------------------------------------------------------------------------
# MCPSkill 测试
# ---------------------------------------------------------------------------

class TestMCPSkill:
    def test_skill_id_format(self) -> None:
        """skill_id 应为 '{server_id}::{tool_name}' 格式。"""
        client = make_mock_client("my_server")
        tool = make_mcp_tool("search")
        skill = MCPSkill(tool=tool, client=client)
        assert skill.skill_id == "my_server::search"

    def test_description_from_tool(self) -> None:
        client = make_mock_client()
        tool = make_mcp_tool("foo", description="Useful tool")
        skill = MCPSkill(tool=tool, client=client)
        assert skill.description == "Useful tool"

    @pytest.mark.asyncio
    async def test_execute_calls_client(self, ctx: RunContext) -> None:
        client = make_mock_client()
        client.call_tool = AsyncMock(return_value="search results")
        tool = make_mcp_tool("search")
        skill = MCPSkill(tool=tool, client=client)

        result = await skill.execute({"query": "LLM"}, ctx)
        client.call_tool.assert_called_once_with("search", {"query": "LLM"})
        assert result["result"] == "search results"

    @pytest.mark.asyncio
    async def test_execute_not_connected_raises(self, ctx: RunContext) -> None:
        client = make_mock_client(connected=False)
        tool = make_mcp_tool("search")
        skill = MCPSkill(tool=tool, client=client)

        with pytest.raises(PluginError, match="not connected"):
            await skill.execute({"query": "test"}, ctx)

    @pytest.mark.asyncio
    async def test_execute_tool_error_raises_plugin_error(self, ctx: RunContext) -> None:
        client = make_mock_client()
        client.call_tool = AsyncMock(side_effect=RuntimeError("tool failed"))
        tool = make_mcp_tool("search")
        skill = MCPSkill(tool=tool, client=client)

        with pytest.raises(PluginError, match="tool failed"):
            await skill.execute({"query": "test"}, ctx)


# ---------------------------------------------------------------------------
# MCPPlugin 测试
# ---------------------------------------------------------------------------

class TestMCPPlugin:
    def _make_plugin(self, server_id: str = "srv") -> tuple[MCPPlugin, AsyncMock]:
        client = make_mock_client(server_id)
        tools = [make_mcp_tool("tool_a"), make_mcp_tool("tool_b")]
        skills = [MCPSkill(tool=t, client=client) for t in tools]
        plugin = MCPPlugin(server_id=server_id, client=client, skills=skills)
        return plugin, client

    def test_plugin_id_format(self) -> None:
        plugin, _ = self._make_plugin("my_server")
        assert plugin.plugin_id == "mcp::my_server"

    def test_skills_list(self) -> None:
        plugin, _ = self._make_plugin()
        assert len(plugin.skills) == 2

    def test_on_load_sets_loaded(self) -> None:
        plugin, _ = self._make_plugin()
        assert plugin._loaded is False
        plugin.on_load()
        assert plugin._loaded is True

    def test_on_unload_clears_loaded(self) -> None:
        plugin, _ = self._make_plugin()
        plugin.on_load()
        plugin.on_unload()
        assert plugin._loaded is False

    @pytest.mark.asyncio
    async def test_aclose_calls_client_close(self) -> None:
        plugin, client = self._make_plugin()
        await plugin.aclose()
        client.close.assert_called_once()


# ---------------------------------------------------------------------------
# MCPRegistry 测试
# ---------------------------------------------------------------------------

class TestMCPRegistry:
    def _make_config(self, server_id: str) -> MCPServerConfig:
        return MCPServerConfig(
            server_id=server_id,
            transport="stdio",
            command="python",
            args=["-m", "my_mcp_server"],
        )

    def test_register_and_get(self) -> None:
        registry = MCPRegistry()
        config = self._make_config("server_1")
        registry.register(config)
        assert registry.get("server_1") is config

    def test_get_unknown_raises(self) -> None:
        registry = MCPRegistry()
        with pytest.raises(KeyError, match="not registered"):
            registry.get("ghost")

    def test_list_server_ids(self) -> None:
        registry = MCPRegistry()
        registry.register(self._make_config("z_server"))
        registry.register(self._make_config("a_server"))
        assert registry.list_server_ids() == ["a_server", "z_server"]

    def test_from_config_dicts(self) -> None:
        dicts = [
            {"server_id": "s1", "transport": "sse", "url": "http://localhost:8080"},
            {"server_id": "s2", "transport": "stdio", "command": "uvx", "args": ["my-server"]},
        ]
        registry = MCPRegistry.from_config_dicts(dicts)
        assert registry.get("s1").url == "http://localhost:8080"
        assert registry.get("s2").command == "uvx"
        assert registry.get("s2").args == ["my-server"]

    def test_all_configs(self) -> None:
        registry = MCPRegistry()
        for i in range(3):
            registry.register(self._make_config(f"s{i}"))
        assert len(registry.all_configs()) == 3
