# Plan: Track warmup_sec for RAG, Serena, Semble
**Date:** 2026-05-29
**Scope:** 2 files changed

---

## Problem

`warmup_sec` in `RunMetrics` is supposed to capture all time spent initializing tools
BEFORE the agent clock starts. Currently three tools are not tracked:

1. **SimpleRAG**: The orchestrator calls `_preingest_rag_tools()` before `runner.run()`,
   so the ingest time exists but is never recorded in `warmup_sec`. The warmup loop
   inside `agno_runner` skips it because `_ingested=True` by that point.

2. **Serena MCP startup**: The MCP subprocess is spawned and `session.initialize()` is
   called (agno_runner.py:415-430) but this time is NOT added to `warmup_total`.

3. **Semble MCP startup**: Same as Serena.

4. **warmup_call** is `None` for both Serena and Semble in `_MCP_TOOL_REGISTRY`, so no
   explicit warmup call is made and the time for that is also 0.

---

## Fix

### File 1: `src/orchestrator/benchmark.py`

#### Change 1a — `_preingest_rag_tools()` returns elapsed time

Find the method `_preingest_rag_tools(self, tools, config_id)`.
It currently calls `tool.ingest()` and logs. Change it to:
- Start a timer before the ingest loop
- Return the total elapsed seconds as a `float`
- If no tools were ingested, return `0.0`

```python
def _preingest_rag_tools(self, tools: list, config_id: str) -> float:
    t0 = time.time()
    ingested = False
    for tool in tools:
        if hasattr(tool, "ingest"):
            ...existing logging...
            tool.ingest()
            ingested = True
    return time.time() - t0 if ingested else 0.0
```

Make sure `import time` is already present at the top of `benchmark.py` (it should be).

#### Change 1b — Pass preingest time to `runner.run()`

In `_run_single_config`, find:
```python
if not self.dry_run:
    self._preingest_rag_tools(tools, config.id)
```

Change to:
```python
preingest_sec = 0.0
if not self.dry_run:
    preingest_sec = self._preingest_rag_tools(tools, config.id)
```

Then pass it to the runner call. Find `runner.run(...)` and add `preingest_sec=preingest_sec`
as a keyword argument.

#### Change 1c — Add `warmup_call` for Serena and Semble

Find `_MCP_TOOL_REGISTRY`. The current entries are:

```python
"serena": McpServerConfig(
    tool_name="serena",
    command="serena",
    args_template=["start-mcp-server", "--project", "{path}"],
),
"semble": McpServerConfig(
    tool_name="semble",
    command="uvx",
    args_template=["--from", "semble[mcp]", "semble", "{path}"],
),
```

Change them to:

```python
"serena": McpServerConfig(
    tool_name="serena",
    command="serena",
    args_template=["start-mcp-server", "--project", "{path}"],
    warmup_call="list_memories",
    warmup_args={},
),
"semble": McpServerConfig(
    tool_name="semble",
    command="uvx",
    args_template=["--from", "semble[mcp]", "semble", "{path}"],
    warmup_call="search",
    warmup_args={"query": "warmup", "limit": 1},
),
```

**IMPORTANT for Semble**: Before hardcoding `"search"`, verify the actual tool name:
Run in WSL:
```bash
wsl bash -c "timeout 8 uvx --from 'semble[mcp]' python -c \"
import importlib, json, pkgutil
try:
    import semble
    print(semble.__file__)
    # Try to find what tools/commands it registers
    for attr in dir(semble):
        print(attr)
except Exception as e:
    print('err:', e)
\" 2>&1 | head -40"
```

Or alternatively, start Semble as MCP server against a temp dir and list its tools via
the MCP protocol listing. The typical Semble tool names from the semble[mcp] package are
likely `search` or `search_code`. If you cannot determine the correct name, use `"search"`
— the warmup code already has error handling that logs a WARNING and continues if the call
fails, so a wrong name will not crash anything.

---

### File 2: `src/features/agent_integration/agno_runner.py`

#### Change 2a — Accept `preingest_sec` parameter in `run()` and `_run_with_mcp()`

In the `run()` method signature, add `preingest_sec: float = 0.0`.
Pass it through to `_run_with_mcp()` (which `run()` calls for MCP configs).

In `_run_with_mcp()` signature, add `preingest_sec: float = 0.0`.

At the start of `_run_with_mcp()`, where `warmup_total = 0.0` is set (line 389),
change to:
```python
warmup_total = preingest_sec  # include orchestrator pre-ingest time
```

#### Change 2b — Time MCP server startup (subprocess spawn + initialize)

In `_run_with_mcp()`, find the MCP session init loop (lines 415-430):
```python
mcp_tool_instances = []
sessions_list = []
for cfg in self.mcp_configs:
    params = StdioServerParameters(...)
    stdio_transport = await stack.enter_async_context(stdio_client(params))
    read, write = stdio_transport[0:2]
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    sessions_list.append(session)
    mcp_inst = MCPTools(session=session)
    await mcp_inst.initialize()
    mcp_tool_instances.append(mcp_inst)
```

Wrap it to time the entire loop:
```python
mcp_tool_instances = []
sessions_list = []
t_mcp_init = time.time()
for cfg in self.mcp_configs:
    params = StdioServerParameters(...)
    ...
    await mcp_inst.initialize()
    mcp_tool_instances.append(mcp_inst)
if self.mcp_configs:
    warmup_total += time.time() - t_mcp_init
```

This adds the total MCP subprocess startup time (all servers) to `warmup_total`.

---

## Notes for Gemini

1. Read the CURRENT file content before making any edits — do not guess indentation.
2. The `_run_with_mcp` method signature may have many parameters; add `preingest_sec: float = 0.0` at the end.
3. The `run()` method currently does NOT call `_run_with_mcp` directly — verify by reading the file how `run()` dispatches to `_run_with_mcp`.
4. The warmup logic for RAG inside `_run_with_mcp` (lines 392-401) stays as-is — it handles the dry-run case where pre-ingest was skipped.
5. Semble warmup_call error is non-fatal (already has try/except). Use best-guess tool name.
6. After the changes, run:
   ```
   wsl bash -c "source /home/artem/.venvs/tools_token_economy/bin/activate && cd /mnt/c/Users/User/a_projects/tools_token_economy && python -m pytest tests/ -q --tb=short 2>&1 | tail -5"
   ```
   All tests must still pass (currently 157).
