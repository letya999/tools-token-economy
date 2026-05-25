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
        args=["start-mcp-server", "--project-from-cwd"],
    )
    
    print("Testing Agno MCPTools discovery (using functions/async_functions)...")
    mcp = MCPTools(server_params=params)
    try:
        await mcp.connect()
        # In Agno, Toolkit stores functions in self.functions and self.async_functions
        print(f"Sync functions count: {len(mcp.functions)}")
        print(f"Async functions count: {len(mcp.async_functions)}")
        
        all_funcs = mcp.get_async_functions()
        print(f"Total available functions: {len(all_funcs)}")
        for name in all_funcs:
            print(f" - {name}")
            
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
    finally:
        await mcp.close()

if __name__ == "__main__":
    asyncio.run(main())
