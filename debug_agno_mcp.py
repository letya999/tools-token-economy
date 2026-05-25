import asyncio
import os
import shutil
import sys
import tempfile
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters

async def main():
    serena_bin = shutil.which("serena")
    params = StdioServerParameters(
        command=serena_bin,
        args=["start-mcp-server", "--project", "."],
    )
    
    print("Connecting to Serena via Agno...")
    async with MCPTools(server_params=params) as mcp_tools:
        print(f"Type of mcp_tools: {type(mcp_tools)}")
        print(f"Has 'tools' attr: {hasattr(mcp_tools, 'tools')}")
        if hasattr(mcp_tools, "tools"):
            print(f"Tool count: {len(mcp_tools.tools)}")
            for t in mcp_tools.tools:
                print(f" - {t}")
        
        # Try another way if tools is empty
        # In some versions it might be mcp_tools.get_tools() or similar
        print(f"Dir of mcp_tools: {dir(mcp_tools)}")

if __name__ == "__main__":
    asyncio.run(main())
