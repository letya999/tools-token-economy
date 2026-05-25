#!/usr/bin/env python3
"""Verify that Agno can connect to a running Serena MCP server and see its tools."""
import asyncio
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


async def main() -> int:
    serena_bin = shutil.which("serena")
    if not serena_bin:
        print("[FAIL] serena binary not found in PATH", file=sys.stderr)
        return 1

    try:
        from agno.tools.mcp import MCPTools
        from mcp import StdioServerParameters
    except ImportError as e:
        print(f"[FAIL] Missing import: {e}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        # Initialize git so serena sees it as a project
        import subprocess
        subprocess.run(["git", "init", "-q"], cwd=tmp)
        with open(os.path.join(tmp, "main.py"), "w") as f:
            f.write("def greet(name: str) -> str:\n    return f'Hello, {name}'\n")
        subprocess.run(["git", "add", "main.py"], cwd=tmp)
        subprocess.run(["git", "commit", "-m", "init", "-q"], cwd=tmp)

        params = StdioServerParameters(
            command=serena_bin,
            args=["start-mcp-server", "--project", tmp],
        )

        try:
            async with MCPTools(server_params=params) as mcp_tools:
                tool_count = len(mcp_tools.tools) if hasattr(mcp_tools, "tools") else 0
                if tool_count == 0:
                    print("[FAIL] Serena MCP: Agno sees 0 tools", file=sys.stderr)
                    return 1
                tool_names = [getattr(t, "name", str(t)) for t in mcp_tools.tools]
                print(f"[OK] Serena MCP — {tool_count} tools: {tool_names[:5]}")
        except Exception as e:
            print(f"[FAIL] Serena MCP connection failed: {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
