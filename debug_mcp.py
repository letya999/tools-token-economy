import asyncio
import shutil
import sys
from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.session import ClientSession

async def main():
    serena_bin = shutil.which("serena")
    if not serena_bin:
        print("serena not found")
        return
    
    params = StdioServerParameters(
        command=serena_bin,
        args=["start-mcp-server", "--project", "."],
    )
    
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"Tools found: {len(tools.tools)}")
            for t in tools.tools:
                print(f" - {t.name}")

if __name__ == "__main__":
    asyncio.run(main())
