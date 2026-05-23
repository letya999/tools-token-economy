"""
Persistent MCP client for connecting to stdio-based MCP servers (Serena, Semble).
Uses a background thread to maintain a persistent connection across synchronous calls.
"""
import asyncio
import threading
import queue
import json
from typing import Any, Optional, List
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class McpToolClient:
    """
    Synchronous facade over a persistent async MCP ClientSession.
    Spawns the MCP server as a subprocess and maintains a single connection.
    """

    def __init__(self, server_command: str, server_args: list[str], cwd: Optional[str] = None):
        self.server_params = StdioServerParameters(
            command=server_command,
            args=server_args,
            cwd=cwd,
        )
        self._request_queue = queue.Queue()
        self._response_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._thread.start()

    def _run_event_loop(self):
        """Entry point for the background thread."""
        try:
            asyncio.run(self._async_main())
        except Exception as e:
            self._response_queue.put(e)

    async def _async_main(self):
        """Persistent async loop running in the background thread."""
        async with stdio_client(self.server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                while not self._stop_event.is_set():
                    try:
                        # Non-blocking check for requests
                        request = self._request_queue.get(timeout=0.1)
                        if request is None:
                            break
                        
                        method, args = request
                        if method == "call_tool":
                            result = await session.call_tool(*args)
                            self._response_queue.put(self._format_result(result))
                        elif method == "list_tools":
                            result = await session.list_tools()
                            self._response_queue.put([t.name for t in result.tools])
                            
                    except queue.Empty:
                        continue
                    except Exception as e:
                        self._response_queue.put(e)

    def _format_result(self, result: Any) -> str:
        """Helper to format MCP result as string."""
        if hasattr(result, "content") and result.content:
            parts = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                else:
                    parts.append(json.dumps(block.__dict__, default=lambda o: str(o)))
            return "\n".join(parts)
        return str(result)

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Synchronously call a tool on the persistent MCP server."""
        self._request_queue.put(("call_tool", (tool_name, arguments)))
        result = self._response_queue.get(timeout=60)
        if isinstance(result, Exception):
            raise result
        return result

    def list_tools(self) -> List[str]:
        """Return list of tool names available on the server."""
        self._request_queue.put(("list_tools", ()))
        result = self._response_queue.get(timeout=10)
        if isinstance(result, Exception):
            return []
        return result

    def close(self):
        """Shut down the background thread and the MCP server."""
        self._stop_event.set()
        self._request_queue.put(None)
        if self._thread.is_alive():
            self._thread.join(timeout=2)
