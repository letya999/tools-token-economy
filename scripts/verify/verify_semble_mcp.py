"""
Verify that Semble MCP server starts and Agno sees its tools.

Semble takes no project path at server startup — the codebase path is passed
as an argument to individual tool calls (search, find_related).
"""
import asyncio
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile


async def main() -> int:
    if not shutil.which("uvx"):
        print("[FAIL] uvx not found in PATH — install uv: https://docs.astral.sh/uv/")
        return 1

    print("[INFO] Starting Semble MCP verification with manual session management...")

    from agno.tools.mcp import MCPTools
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, check=True)
        for name, code in [
            ("api.py", "def get_user(user_id: int):\n    pass\n"),
            ("models.py", "class Order:\n    status: str\n"),
        ]:
            with open(os.path.join(tmp, name), "w") as f:
                f.write(code)
        subprocess.run(["git", "add", "."], cwd=tmp, check=True)
        subprocess.run(["git", "commit", "-m", "init", "-q"], cwd=tmp, check=True)

        params = StdioServerParameters(
            command="uvx",
            args=["--from", "semble[mcp]", "semble"],
        )

        try:
            async with contextlib.AsyncExitStack() as stack:
                stdio_transport = await stack.enter_async_context(stdio_client(params))
                read, write = stdio_transport[0], stdio_transport[1]
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()

                mcp_tools = MCPTools(session=session)
                await mcp_tools.initialize()

                tool_names = list(mcp_tools.functions.keys())
                if not tool_names:
                    print("[FAIL] Agno sees 0 Semble tools")
                    return 1

                print(f"[OK] Agno sees {len(tool_names)} Semble tools: {tool_names}")
                return 0

        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] Semble MCP session failed: {exc}")
            import traceback
            traceback.print_exc()
            return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
