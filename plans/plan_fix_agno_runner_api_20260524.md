# Plan: Fix AgnoRunner to match Agno 2.6.9 API

## Problem
All 20 benchmark configs fail with:
```
TypeError: Agent.__init__() got an unexpected keyword argument 'show_tool_calls'
```

The runner was written against a different Agno API version. Agno 2.6.9 has:
- No `show_tool_calls` param on `Agent`
- No `max_turns` param on `Agent` → use `tool_call_limit` instead
- `RunOutput` lives in `agno.run.agent`, not `agno.agent`
- `RunOutput.metrics` is `RunMetrics` with direct `.input_tokens` / `.output_tokens` attrs
- `RunOutput.tools` is `List[ToolExecution]` with `.tool_name` and `.tool_call_error` fields
  (better than parsing raw messages for tool counting)

## File to modify: `src/features/agent_integration/agno_runner.py`

### Fix 1 — imports (top of file)
Change:
```python
from agno.agent import Agent, RunOutput
```
To:
```python
from agno.agent import Agent
from agno.run.agent import RunOutput
```

### Fix 2 — Agent constructor (inside `run()` method)
Change:
```python
agent = Agent(
    model=OpenAIChat(id=model_id),
    tools=agno_tools_list,
    instructions=[
        f"You are a coding agent working in the repository at: {worktree_path}",
        "Complete the task using only the tools provided.",
        "When done, output exactly: TASK_COMPLETE",
    ],
    markdown=False,
    show_tool_calls=False,
    max_turns=self.config.max_steps
)
```
To:
```python
agent = Agent(
    model=OpenAIChat(id=model_id),
    tools=agno_tools_list,
    instructions=[
        f"You are a coding agent working in the repository at: {worktree_path}",
        "Complete the task using only the tools provided.",
        "When done, output exactly: TASK_COMPLETE",
    ],
    markdown=False,
    tool_call_limit=self.config.max_steps,
)
```

### Fix 3 — metrics extraction (inside `run()` method)
Change:
```python
if response.metrics:
    metrics_data["input_tokens"] = getattr(response.metrics, "input_tokens", 0)
    metrics_data["output_tokens"] = getattr(response.metrics, "output_tokens", 0)
```
To:
```python
if response.metrics:
    metrics_data["input_tokens"] = response.metrics.input_tokens or 0
    metrics_data["output_tokens"] = response.metrics.output_tokens or 0
```

### Fix 4 — tool call counting (replace message loop)
Replace the entire message-iteration block:
```python
# Count tool calls and tool tokens from messages
for msg in (response.messages or []):
    role = getattr(msg, "role", None)
    content = getattr(msg, "content", "")
    
    if role == "assistant":
        metrics_data["model_calls"] += 1
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            metrics_data["tool_calls"] += len(tool_calls)
            for tc in tool_calls:
                # tc is often a dict or has function attribute
                func = tc.get("function", {}) if isinstance(tc, dict) else getattr(tc, "function", {})
                name = func.get("name", "") if isinstance(func, dict) else getattr(func, "name", "")
                
                if name in {"read", "read_all", "glob", "tree_sitter", "repo_map", "simple_rag", "lsp_symbols"}:
                    metrics_data["files_read"] += 1
                elif name in {"patch", "write"}:
                    metrics_data["files_changed"] += 1
    
    elif role == "tool":
        metrics_data["tool_tokens"] += self._count_tokens(str(content))
        if "Error executing tool" in str(content):
            metrics_data["errors"] += 1
```

With this cleaner version using `response.tools` (ToolExecution list) and messages for token counting:
```python
# Count model calls from assistant messages
for msg in (response.messages or []):
    role = getattr(msg, "role", None)
    content = getattr(msg, "content", "")
    if role == "assistant":
        metrics_data["model_calls"] += 1
    elif role == "tool":
        metrics_data["tool_tokens"] += self._count_tokens(str(content))

# Count tool calls from ToolExecution list (cleaner than parsing raw messages)
_read_tools = {"read", "read_all", "glob", "tree_sitter", "repo_map", "simple_rag", "lsp_symbols"}
_write_tools = {"patch", "write"}
for tool_exec in (response.tools or []):
    metrics_data["tool_calls"] += 1
    name = tool_exec.tool_name or ""
    if name in _read_tools:
        metrics_data["files_read"] += 1
    elif name in _write_tools:
        metrics_data["files_changed"] += 1
    if tool_exec.tool_call_error:
        metrics_data["errors"] += 1
```

### Fix 5 — content access
Change:
```python
success = "TASK_COMPLETE" in (response.content or "")
```
To (use get_content_as_string for safety):
```python
content_str = response.get_content_as_string() if hasattr(response, "get_content_as_string") else (str(response.content) if response.content else "")
success = "TASK_COMPLETE" in content_str
```

And the fallback token counting:
```python
if metrics_data["output_tokens"] == 0:
    metrics_data["output_tokens"] = self._count_tokens(content_str)
```

## What NOT to change
- `_run_mock()` — works as-is
- `_count_tokens()` — works as-is
- `_extract_model_id()` — works as-is
- `_build_agno_tools()` — works as-is
- All other files

## After fixing
Run a quick import check in WSL:
```bash
cd /mnt/c/Users/User/a_projects/tools_token_economy
UV_PROJECT_ENVIRONMENT=/tmp/tte_venv uv run python -c "from src.features.agent_integration.agno_runner import AgnoRunner; print('OK')"
```

Then run the first config only to verify end-to-end with real API.
