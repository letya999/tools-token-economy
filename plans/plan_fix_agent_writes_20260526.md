# Plan: Fix Agent Code Writing + Patch File Bug

## Problem Summary

Three bugs cause `task_solved_score = 0.00` for all configs and 8/20 failures:

1. **Agent doesn't write code**: Instructions never explicitly require calling `write`/`patch` before `TASK_COMPLETE`. Agent reads files, figures out changes mentally, then says "TASK_COMPLETE" without saving.
2. **Patch filename mismatch**: `agno_runner._validate_run()` saves `changes.patch`; `benchmark.py` reads `final.patch`. Judge always receives `None` diff → scores 0.
3. **No per-response token cap**: No `max_tokens` guard → runaway responses (07_grep: 205K tokens, 03_gemini: 325K tokens).

## Files to Modify

### 1. `src/features/agent_integration/agno_runner.py`

**Change A — Strengthen agent instructions** (both the `run()` and `_run_with_mcp()` agent construction blocks, which both contain duplicate `instructions=[...]`):

Replace the current instructions list with one that explicitly requires writing:

```python
instructions=[
    f"You are a coding agent working in the repository at: {worktree_path}",
    "Complete the task using only the tools provided.",
    "Always use RELATIVE file paths (relative to the repository root) when calling file tools. Never use absolute paths.",
    "MANDATORY: You MUST call the `write` or `patch` tool to save your code changes to disk before saying TASK_COMPLETE. Reading files and thinking about changes is not enough - you must persist changes with a tool call.",
    "Workflow: (1) Use retrieval tools to understand the codebase. (2) Write your changes using `write` (full file) or `patch` (unified diff). (3) Verify by reading the file back. (4) Output exactly: TASK_COMPLETE",
    "If a tool returns an error, try a different approach - do not repeat the exact same tool call.",
    "Never output TASK_COMPLETE if you have not called write or patch at least once.",
],
```

**Change B — Fix patch filename**: In `_validate_run()`, change:
```python
patch_path = os.path.join(self.run_dir, "changes.patch")
```
to:
```python
patch_path = os.path.join(self.run_dir, "final.patch")
```

**Change C — Add per-response token cap**: In `OpenAIChat(id=model_id)` instantiation (both sync and async paths), add a reasonable token cap:
```python
OpenAIChat(id=model_id, max_tokens=4096)
```
This prevents single responses from exploding. 4096 output tokens is sufficient for writing a test function. The model can still make multiple tool calls (controlled by `tool_call_limit`).

### 2. `src/features/prompt_builder.py`

**Change A — Add write/patch reminder to prefix**: The current code strips `write`/`patch` from the displayed tool list. Instead, show them as a required section:

```python
def build_tool_restriction_prefix(config: AgentConfig) -> str:
    retrieval_tools = sorted(set(config.tools) - {"test", "patch", "write"})
    write_tools = [t for t in config.tools if t in ("write", "patch")]
    
    if not retrieval_tools and not write_tools:
        return ""

    lines = [
        "[BENCHMARK TOOL CONFIG]",
        f"Configuration: {config.name} (archetype: {config.archetype})",
    ]
    if retrieval_tools:
        lines.append(f"Retrieval tools available: {', '.join(retrieval_tools)}")
    if write_tools:
        lines.append(f"Write tools (MANDATORY - use to save changes): {', '.join(write_tools)}")
    lines += [
        "Use ONLY the listed retrieval strategies. Avoid alternatives not in this list.",
        "[END CONFIG]\n",
    ]
    return "\n".join(lines)
```

### 3. Tests to update

**`tests/`** — search for any test that references `"changes.patch"` and update to `"final.patch"`. Run grep first:
```
grep -r "changes.patch" tests/
```

## Acceptance Criteria

After the fix:
- Agent must call `write` or `patch` before `TASK_COMPLETE` (verifiable in conversation log)
- `results/run_*/final.patch` exists and is non-empty for passing configs
- LLM judge receives actual diff content (not `None`)
- `task_solved_score > 0.0` for configs where tests pass
- No individual config exceeds ~16K output tokens per response

## Implementation Notes

- Both `run()` (non-MCP path) and `_run_with_mcp()` (MCP path) create an `Agent(...)` separately with duplicate instructions — both must be updated
- The `max_tokens=4096` only limits per-response output, not total context. It's a guard against runaway single responses, not a total budget cap
- Do NOT change the task description in `benchmark_configs.yaml` — the instructions fix is sufficient
- Do NOT modify `_validate_run` logic beyond the filename fix
