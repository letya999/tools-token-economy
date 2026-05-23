"""
Async MCP client for connecting to stdio-based MCP servers (Serena, Semble).
"""
import asyncio
from typing import Any, Optional
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class McpToolClient:
    """
    Synchronous facade over async MCP ClientSession.
    Spawns the MCP server as a subprocess and communicates via stdio.
    """

    def __init__(self, server_command: str, server_args: list[str], cwd: Optional[str] = None):
        self.server_params = StdioServerParameters(
            command=server_command,
            args=server_args,
            cwd=cwd,
        )

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Synchronously call a tool on the MCP server and return result as string."""
        try:
            return asyncio.run(self._async_call_tool(tool_name, arguments))
        except Exception as e:
            return f"Error calling tool {tool_name}: {e}"

    async def _async_call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        async with stdio_client(self.server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                # MCP results can be a list of content blocks
                if hasattr(result, "content") and result.content:
                    parts = []
                    for block in result.content:
                        if hasattr(block, "text"):
                            parts.append(block.text)
                        else:
                            parts.append(str(block))
                    return "\n".join(parts)
                return str(result)

    def list_tools(self) -> list[str]:
        """Return list of tool names available on the server."""
        try:
            return asyncio.run(self._async_list_tools())
        except Exception:
            return []

    async def _async_list_tools(self) -> list[str]:
        async with stdio_client(self.server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [t.name for t in tools.tools]
