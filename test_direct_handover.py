import asyncio
import shutil
import sys
import logging
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters
import traceback

# Force agno logging to DEBUG
logger = logging.getLogger("agno")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))
logger.addHandler(handler)

async def main():
    serena_bin = shutil.which("serena")
    params = StdioServerParameters(
        command=serena_bin,
        args=["start-mcp-server", "--project", "."],
    )
    
    print("Direct MCP Client Test...")
    from mcp.client.stdio import stdio_client
    from mcp.client.session import ClientSession
    
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("Session initialized")
                tools = await session.list_tools()
                print(f"Tools found directly: {len(tools.tools)}")
                
                print("Now trying to hand this session to MCPTools...")
                mcp = MCPTools(session=session)
                # If we provide a session, MCPTools should just call build_tools
                await mcp.initialize()
                print(f"MCPTools initialized. Tools count: {len(mcp.functions)}")
                
    except Exception as e:
        print(f"Direct test failed: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
