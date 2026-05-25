import asyncio
import shutil
import sys
from agno.agent import Agent
from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters
import os

async def main():
    serena_bin = shutil.which("serena")
    params = StdioServerParameters(
        command=serena_bin,
        args=["start-mcp-server", "--project-from-cwd"],
    )
    
    print("Testing Agno Agent with Serena MCP...")
    # Manually connect toolkit since Agent doesn't seem to do it automatically or fails quietly
    mcp = MCPTools(server_params=params)
    await mcp.connect()
    print(f"Tools count: {len(mcp.tools)}")
    
    if not os.getenv("OPENAI_API_KEY"):
        print("Skipping LLM call: OPENAI_API_KEY not set")
        await mcp.close()
        return

    agent = Agent(
        tools=[mcp],
        instructions="You are a helper.",
        markdown=True
    )
    
    await agent.aprint_response("What tools do you have? Just list them.")
    await mcp.close()

if __name__ == "__main__":
    asyncio.run(main())
