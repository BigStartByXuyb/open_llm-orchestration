"""
MCPSkill — 将单个 MCP 工具包装为 SkillProtocol
MCPSkill — Wraps a single MCP tool as SkillProtocol.

Layer 4: Only imports from shared/ and mcp/client.py.

MCPSkill 对 orchestration 层完全透明 — 它就是一个普通的 Skill。
MCPSkill is completely transparent to the orchestration layer — it's just a regular Skill.
"""

from __future__ import annotations

from typing import Any

from mcp.types import Tool

from orchestration.shared.errors import PluginError
from orchestration.shared.types import RunContext
from orchestration.mcp.client import MCPClient


class MCPSkill:
    """
    MCP 工具适配器 — 实现 SkillProtocol
    MCP tool adapter — implements SkillProtocol.

    每个 MCPSkill 对应一个 MCP 服务器上的工具，
    调用时通过共享 MCPClient 发出 tool_call 请求。
    Each MCPSkill corresponds to one tool on an MCP server,
    calls are dispatched via the shared MCPClient.
    """

    def __init__(self, tool: Tool, client: MCPClient) -> None:
        self._tool = tool
        self._client = client

    @property
    def skill_id(self) -> str:
        """Skill ID = "{server_id}::{tool_name}" 确保全局唯一 / globally unique."""
        return f"{self._client.server_id}::{self._tool.name}"

    @property
    def description(self) -> str:
        return self._tool.description or ""

    @property
    def input_schema(self) -> dict[str, Any]:
        # MCP Tool.inputSchema 已是 JSON Schema dict
        # MCP Tool.inputSchema is already a JSON Schema dict
        schema = self._tool.inputSchema
        if hasattr(schema, "model_dump"):
            return schema.model_dump()
        return dict(schema) if schema else {}

    @property
    def output_schema(self) -> dict[str, Any]:
        # MCP 不定义输出 schema，提供通用结构 / MCP doesn't define output schema; provide generic
        return {"type": "object", "properties": {"result": {"type": "string"}}}

    async def execute(self, inputs: dict[str, Any], context: RunContext) -> dict[str, Any]:
        """
        通过 MCPClient 调用 MCP 工具
        Call the MCP tool via MCPClient.

        Raises / 抛出:
            PluginError: 工具调用失败 / On tool call failure
        """
        if not self._client.is_connected:
            raise PluginError(
                f"MCPClient '{self._client.server_id}' is not connected",
                skill_id=self.skill_id,
            )

        try:
            text_result = await self._client.call_tool(self._tool.name, inputs)
        except Exception as exc:
            raise PluginError(
                f"MCP tool '{self._tool.name}' failed: {exc}",
                skill_id=self.skill_id,
            ) from exc

        return {"result": text_result}
