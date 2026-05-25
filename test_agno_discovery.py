import asyncio
import shutil
import sys
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters

async def main():
    serena_bin = shutil.which("serena")
    params = StdioServerParameters(
        command=serena_bin,
        args=["start-mcp-server", "--project", "."],
    )
    
    print("Testing Agno MCPTools discovery...")
    async with MCPTools(server_params=params) as mcp:
        print(f"Toolkit initialized. Tools count: {len(mcp.tools)}")
        for t in mcp.tools:
            # Agno tools might be instances of a wrapper class
            name = getattr(t, "name", str(t))
            print(f" - {name}")

if __name__ == "__main__":
    asyncio.run(main())
