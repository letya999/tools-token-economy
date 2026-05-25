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
    
    print("Testing Agno MCPTools discovery with internal DEBUG...")
    mcp = MCPTools(server_params=params)
    try:
        # Patch build_tools to see what's happening
        original_build = mcp.build_tools
        async def build_tools_debug():
            print("Entering build_tools_debug...")
            try:
                # We need to call it on the instance
                await original_build()
                print("Exited original build_tools successfully")
            except Exception as e:
                print(f"Original build_tools failed: {e}")
                traceback.print_exc()
                raise
        
        # Method binding simulation
        mcp.build_tools = build_tools_debug
        
        await mcp.connect()
        print(f"Tools count: {len(mcp.functions)}")
            
    except Exception as e:
        print(f"Error: {e}")
        # toolkit connect logs error but doesn't raise, let's see if initialize raises
        try:
            await mcp.initialize()
        except Exception as e2:
            print(f"Initialize error: {e2}")
            traceback.print_exc()
    finally:
        await mcp.close()

if __name__ == "__main__":
    asyncio.run(main())
