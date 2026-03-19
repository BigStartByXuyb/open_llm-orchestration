"""
MCPRegistry — MCP 服务器连接注册表
MCPRegistry — MCP server connection registry.

Layer 4: Only imports from shared/ and mcp/client.py.

存储 MCPServerConfig 集合，供 wiring/container.py 在启动时遍历连接。
Stores the set of MCPServerConfig objects; wiring/container.py iterates them on startup.
"""

from __future__ import annotations

from orchestration.mcp.client import MCPServerConfig


class MCPRegistry:
    """
    MCP 服务器配置注册表
    MCP server configuration registry.

    持有所有已知 MCP server 的连接配置；实际连接由 wiring 层负责。
    Holds connection configs for all known MCP servers; actual connection done by wiring layer.
    """

    def __init__(self) -> None:
        self._configs: dict[str, MCPServerConfig] = {}

    def register(self, config: MCPServerConfig) -> None:
        """注册 MCP server 配置 / Register MCP server config."""
        self._configs[config.server_id] = config

    def get(self, server_id: str) -> MCPServerConfig:
        """获取配置；不存在时抛 KeyError / Get config; raises KeyError if not found."""
        if server_id not in self._configs:
            raise KeyError(f"MCP server '{server_id}' not registered")
        return self._configs[server_id]

    def list_server_ids(self) -> list[str]:
        """列出所有已注册的 server ID / List all registered server IDs."""
        return sorted(self._configs.keys())

    def all_configs(self) -> list[MCPServerConfig]:
        """返回所有配置 / Return all configs."""
        return list(self._configs.values())

    @classmethod
    def from_config_dicts(cls, config_dicts: list[dict]) -> "MCPRegistry":
        """
        从配置字典列表构建注册表（供 wiring 层从 Settings 解析）
        Build registry from list of config dicts (for wiring layer to parse from Settings).

        Expected dict fields: server_id, transport, command/args/env or url.
        """
        registry = cls()
        for d in config_dicts:
            config = MCPServerConfig(
                server_id=d["server_id"],
                transport=d.get("transport", "stdio"),
                command=d.get("command", ""),
                args=d.get("args", []),
                env=d.get("env", {}),
                url=d.get("url", ""),
            )
            registry.register(config)
        return registry
