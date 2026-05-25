import asyncio
import shutil
import sys
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters
import traceback

async def main():
    serena_bin = shutil.which("serena")
    params = StdioServerParameters(
        command=serena_bin,
        args=["start-mcp-server", "--project", "."],
    )
    
    print("Testing Agno MCPTools discovery...")
    mcp = MCPTools(server_params=params)
    try:
        # Manually connect to see exactly where it fails
        await mcp.connect()
        print(f"Toolkit connected. Tools count: {len(mcp.tools)}")
        for t in mcp.tools:
            name = getattr(t, "name", str(t))
            print(f" - {name}")
    except Exception as e:
        print(f"Error during connect: {e}")
        traceback.print_exc()
    finally:
        await mcp.close()

if __name__ == "__main__":
    asyncio.run(main())
