"""
Verify that Serena MCP server starts correctly and Agno sees its tools.

Diagnosis checklist:
  - serena binary in PATH
  - ~/.serena/serena_config.yml exists (absence causes 14-field pydantic ValidationError)
  - MCP server starts and exposes > 0 tools to Agno's MCPTools
"""
import asyncio
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile


async def main() -> int:
    serena_bin = shutil.which("serena")
    if not serena_bin:
        print("[FAIL] serena binary not found in PATH")
        print("       Run: bash scripts/install/install_serena.sh")
        return 1

    global_cfg = os.path.join(os.path.expanduser("~"), ".serena", "serena_config.yml")
    if not os.path.isfile(global_cfg):
        print(f"[FAIL] Global config missing: {global_cfg}")
        print("       Run: bash scripts/install/install_serena.sh")
        return 1

    print(f"[INFO] serena binary: {serena_bin}")
    print(f"[INFO] global config: {global_cfg}")
    print("[INFO] Starting MCP verification with manual session management...")

    from agno.tools.mcp import MCPTools
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    with tempfile.TemporaryDirectory() as tmp:
        # Minimal Python project for Serena to analyse
        subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp, check=True)
        with open(os.path.join(tmp, "main.py"), "w") as f:
            f.write("def greet(name: str) -> str:\n    return f'Hello, {name}'\n")
        subprocess.run(["git", "add", "main.py"], cwd=tmp, check=True)
        subprocess.run(["git", "commit", "-m", "init", "-q"], cwd=tmp, check=True)

        # Minimal project-level Serena config so LSP doesn't wait for Python LS startup
        serena_project_dir = os.path.join(tmp, ".serena")
        os.makedirs(serena_project_dir, exist_ok=True)
        with open(os.path.join(serena_project_dir, "project.yml"), "w") as f:
            f.write(
                "project_name: verify_test\n"
                "languages: []\n"  # empty = no LSP, fast startup for smoke test
                "encoding: utf-8\n"
                "read_only: false\n"
                "excluded_tools: []\n"
                "included_optional_tools: []\n"
                "fixed_tools: []\n"
            )

        params = StdioServerParameters(
            command=serena_bin,
            args=["start-mcp-server", "--project", tmp],
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
                    print("[FAIL] Agno sees 0 Serena tools — session initialized but no functions registered")
                    return 1

                print(f"[OK] Agno sees {len(tool_names)} Serena tools")
                print(f"     Sample: {tool_names[:5]}")
                return 0

        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] MCP session failed: {exc}")
            import traceback
            traceback.print_exc()
            return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
