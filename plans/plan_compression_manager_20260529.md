# Plan: Add CompressionManager and ShellTool Truncation

**Date**: 2026-05-29
**Goal**: Fix O(n²) context accumulation in Agno agents by adding CompressionManager; also truncate ShellTool output.

---

## Change 1 — `src/features/agent_integration/agno_runner.py`

### 1a. Add import at the top of the file (after existing agno imports)

Find the block:
```python
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from agno.tools import tool as agno_tool
from agno.tools.mcp import MCPTools
```

Add one line after it:
```python
from agno.compression.manager import CompressionManager
```

### 1b. Modify `_build_agent()` method

Find the current `_build_agent` method body (starts at line ~119):
```python
    def _build_agent(self, model_id: str, tools: list, worktree_path: str) -> Agent:
        effective_limit = min(self.config.max_steps, self.max_iterations)
        return Agent(
            model=OpenAIChat(id=model_id, max_tokens=4096),
            tools=tools,
            instructions=[
```

Replace the entire `_build_agent` method with:
```python
    def _build_agent(self, model_id: str, tools: list, worktree_path: str) -> Agent:
        effective_limit = min(self.config.max_steps, self.max_iterations)
        compression_manager = CompressionManager(
            model=OpenAIChat(id=model_id),
            compress_tool_results=True,
            compress_token_limit=6000,
        )
        return Agent(
            model=OpenAIChat(id=model_id, max_tokens=4096),
            tools=tools,
            compression_manager=compression_manager,
            instructions=[
                f"You are a coding agent working in the repository at: {worktree_path}",
                "Complete the task using only the tools provided.",
                "Always use RELATIVE file paths (relative to the repository root) when calling file tools. Never use absolute paths.",
                "MANDATORY: You MUST call the `write` or `patch` tool to save your code changes to disk before saying TASK_COMPLETE. Reading files and thinking about changes is not enough - you must persist changes with a tool call.",
                "Workflow: (1) Use retrieval tools to understand the codebase. (2) Write your changes using `write` (full file) or `patch` (unified diff). (3) Verify by reading the file back. (4) Output exactly: TASK_COMPLETE",
                "If a tool returns an error, try a different approach - do not repeat the exact same tool call.",
                "Never output TASK_COMPLETE if you have not called write or patch at least once.",
                "CRITICAL: NEVER delete, truncate, or overwrite existing code. When adding to an existing file, preserve ALL existing content. If using 'write', copy all original content and append/insert only your new code. If using 'patch', only add lines — NEVER remove existing functions, classes, or tests.",
                "CRITICAL: NEVER remove or replace existing tests. The test file already contains tests. You must ADD a new test without touching any existing test.",
                "Efficiency: Use the `shell` tool's `multi_cmd` parameter to run multiple related commands in a single turn (e.g. `ls` then `cat`).",
            ],
            markdown=False,
            tool_call_limit=effective_limit,
        )
```

---

## Change 2 — `src/features/tool_registry/shell_tool.py`

Find the end of `execute()` method, currently:
```python
        return self.format_result("\n\n".join(full_output))
```

Replace with:
```python
        _MAX_SHELL_OUTPUT = 15_000
        combined = "\n\n".join(full_output)
        if len(combined) > _MAX_SHELL_OUTPUT:
            combined = combined[:_MAX_SHELL_OUTPUT] + f"\n\n[OUTPUT TRUNCATED: shell output exceeded {_MAX_SHELL_OUTPUT} chars]"
        return self.format_result(combined)
```

---

## Verification

After making the changes, verify:
1. `grep -n "CompressionManager" src/features/agent_integration/agno_runner.py` — should show 2 lines (import + usage)
2. `grep -n "_MAX_SHELL_OUTPUT" src/features/tool_registry/shell_tool.py` — should show the constant

No tests need to change. The CompressionManager is transparent to the rest of the system.

## Files to modify

1. `src/features/agent_integration/agno_runner.py`
2. `src/features/tool_registry/shell_tool.py`
