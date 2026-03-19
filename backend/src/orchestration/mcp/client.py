"""
MCPClient — MCP 协议客户端（持久连接，支持 stdio / SSE transport）
MCPClient — MCP protocol client (persistent connection, stdio / SSE transport).

Layer 4: Only imports from shared/.

设计 / Design:
  使用 contextlib.AsyncExitStack 维护持久连接，支持跨多次请求复用。
  Uses contextlib.AsyncExitStack for persistent connection, reusable across requests.

  transport:
    "stdio" — 启动子进程，通过 stdin/stdout 通信（适合本地 MCP server）
              Spawn subprocess, communicate via stdin/stdout (local MCP server)
    "sse"   — 通过 HTTP SSE 连接远程 MCP server
              Connect to remote MCP server via HTTP SSE

Usage / 使用方式:
  client = MCPClient(config)
  await client.connect()
  tools = await client.list_tools()
  result = await client.call_tool("search", {"query": "hello"})
  await client.close()
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.client.sse import sse_client
from mcp.types import Tool

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """
    MCP 服务器连接配置
    MCP server connection configuration.
    """

    server_id: str
    transport: Literal["stdio", "sse"] = "stdio"

    # stdio transport params / stdio transport 参数
    command: str = ""                              # 可执行文件路径 / Executable path
    args: list[str] = field(default_factory=list)  # 命令行参数 / CLI arguments
    env: dict[str, str] = field(default_factory=dict)  # 额外环境变量 / Extra env vars

    # SSE transport params / SSE transport 参数
    url: str = ""  # MCP server URL / MCP 服务器 URL


class MCPClient:
    """
    MCP 协议客户端 — 连接到 MCP 服务器并调用工具
    MCP protocol client — connect to MCP server and call tools.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self._config = config
        self._stack: contextlib.AsyncExitStack | None = None
        self._session: ClientSession | None = None

    @property
    def server_id(self) -> str:
        return self._config.server_id

    @property
    def is_connected(self) -> bool:
        return self._session is not None

    async def connect(self) -> None:
        """
        连接到 MCP 服务器并完成握手
        Connect to MCP server and complete handshake.

        Raises / 抛出:
            Exception: 连接失败时 / On connection failure
        """
        if self.is_connected:
            logger.debug("MCPClient '%s' already connected", self.server_id)
            return

        self._stack = contextlib.AsyncExitStack()

        try:
            if self._config.transport == "stdio":
                params = StdioServerParameters(
                    command=self._config.command,
                    args=self._config.args,
                    env=self._config.env or None,
                )
                read, write = await self._stack.enter_async_context(stdio_client(params))
            else:
                read, write = await self._stack.enter_async_context(
                    sse_client(self._config.url)
                )

            self._session = await self._stack.enter_async_context(
                ClientSession(read, write)
            )
            await self._session.initialize()
            logger.info("MCPClient '%s' connected (%s)", self.server_id, self._config.transport)
        except Exception:
            await self._cleanup()
            raise

    async def close(self) -> None:
        """
        关闭与 MCP 服务器的连接
        Close connection to MCP server.
        """
        await self._cleanup()
        logger.info("MCPClient '%s' disconnected", self.server_id)

    async def _cleanup(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
        self._session = None

    def _require_connected(self) -> ClientSession:
        if self._session is None:
            raise RuntimeError(f"MCPClient '{self.server_id}' is not connected")
        return self._session

    async def list_tools(self) -> list[Tool]:
        """
        列举 MCP 服务器提供的所有工具
        List all tools provided by the MCP server.
        """
        session = self._require_connected()
        result = await session.list_tools()
        return result.tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        """
        调用 MCP 工具，返回文本内容（拼接所有 TextContent）
        Call an MCP tool, return text content (concatenation of all TextContent).

        Raises / 抛出:
            RuntimeError: 未连接时 / When not connected
            Exception: 工具调用失败时 / On tool call failure
        """
        session = self._require_connected()
        result = await session.call_tool(name, arguments or {})

        if result.isError:
            # 提取错误信息 / Extract error message
            texts = [
                c.text for c in result.content
                if hasattr(c, "text") and c.text
            ]
            raise RuntimeError(
                f"MCP tool '{name}' returned error: " + "; ".join(texts)
            )

        texts = [
            c.text for c in result.content
            if hasattr(c, "text") and c.text
        ]
        return "\n".join(texts)

    async def __aenter__(self) -> "MCPClient":
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
