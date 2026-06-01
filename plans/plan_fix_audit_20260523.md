# Plan: Fix All Audit Issues + OpenCode + MCP Clients
Generated: 2026-05-23

## Context
Full audit found ~35% of spec unimplemented or broken. This plan fixes everything:
bugs, missing tools, fake stubs, missing metrics, missing ranking report, model version,
deprecated library, and replaces fake OpenCodeRunner with real OpenCode CLI subprocess wrapper.

The project runs in **WSL2 Ubuntu**. All shell commands must be POSIX bash.
Project path in WSL: `/mnt/c/Users/User/a_projects/tools_token_economy`

---

## 1. Fix `pyproject.toml`

**File:** `pyproject.toml`

Replace `google-generativeai` with `google-genai`. Add `mcp` and `jedi` dependencies.

Final dependencies list:
```
google-genai>=1.0.0
pydantic>=2.13.4
pytest>=9.0.3
pytest-mock>=3.15.1
pyyaml>=6.0.3
rank-bm25>=0.2.2
ruff>=0.15.14
tiktoken>=0.13.0
tree-sitter>=0.25.2
tree-sitter-python>=0.25.0
mcp>=1.0.0
jedi>=0.19.0
```

---

## 2. Fix `src/core/models.py`

**Changes:**
- Add `success: bool` field to `EvalResult` (this is the critical bug from audit)
- Add missing spec metrics to `RunMetrics`:
  - `tests_passed: int = 0`
  - `files_read: int = 0`
  - `files_changed: int = 0`
  - `patch_lines: int = 0`
  - `errors: int = 0`
- Add `success_per_token` as `@computed_field` on `RunMetrics`:
  ```python
  @computed_field
  @property
  def success_per_token(self) -> float:
      if self.total_tokens == 0:
          return 0.0
      return 1.0 / self.total_tokens if self.success else 0.0
  ```

---

## 3. Fix `configs/benchmark_configs.yaml`

**Change:** Replace ALL occurrences of `gemini-1.5-flash` with `gemini-2.5-flash`.
All 20 configs must use `gemini-2.5-flash`.

---

## 4. Replace `src/features/agent_integration/opencode_runner.py`

**Purpose:** Remove the fake DIY agent loop and replace with a real OpenCode CLI subprocess wrapper.

**OpenCode install (WSL):** `npm install -g opencode`
**OpenCode invocation:** `opencode run --print --format json "<task>"`

**New implementation:**

```python
"""
OpenCode CLI subprocess wrapper.

Requires: npm install -g opencode (in WSL)
"""
import subprocess
import json
import time
import tiktoken
from typing import List
from src.core.models import AgentConfig, RunMetrics
from src.core.tools import Tool
from src.features.rate_limiter import RateLimiter


class OpenCodeRunner:
    """
    Runs OpenCode CLI as a subprocess and collects metrics from its JSONL output.
    In mock/dry-run mode, skips the CLI entirely.
    """

    def __init__(self, config: AgentConfig, tools: List[Tool], mock: bool = False):
        self.config = config
        self.tools = tools
        self.mock = mock
        self._tokenizer = tiktoken.get_encoding("cl100k_base")
        self._rate_limiter = RateLimiter(requests_per_minute=10)

    def _count_tokens(self, text: str) -> int:
        if not text:
            return 0
        return len(self._tokenizer.encode(text))

    def _build_tool_flags(self) -> List[str]:
        """Translate tool names to opencode CLI permission flags."""
        # opencode uses --allow-* flags for tool permissions
        # Map our tool names to opencode permission categories
        tool_flag_map = {
            "read": "--allow-read",
            "read_all": "--allow-read",
            "write": "--allow-write",
            "patch": "--allow-write",
            "glob": "--allow-read",
            "rg": "--allow-run",
            "grep": "--allow-run",
            "git_grep": "--allow-run",
            "ugrep": "--allow-run",
            "semgrep": "--allow-run",
            "tree_sitter": "--allow-read",
            "repo_map": "--allow-read",
            "simple_rag": "--allow-read",
            "serena": "--allow-run",
            "semble": "--allow-run",
            "shell": "--allow-run",
            "lsp_symbols": "--allow-read",
        }
        flags = set()
        for tool_name in [t.name for t in self.tools]:
            flag = tool_flag_map.get(tool_name)
            if flag:
                flags.add(flag)
        return list(flags)

    def run(self, task_description: str, worktree_path: str = ".") -> RunMetrics:
        """
        Execute the task via OpenCode CLI and collect metrics.
        """
        start_time = time.time()

        if self.mock:
            # Dry-run: simulate a minimal successful run
            simulated_output = f"Task: {task_description}\nTASK_COMPLETE"
            token_count = self._count_tokens(simulated_output)
            return RunMetrics(
                success=True,
                eval_score=1.0,
                input_tokens=token_count,
                output_tokens=self._count_tokens("TASK_COMPLETE"),
                tool_tokens=0,
                duration_sec=time.time() - start_time,
                model_calls=1,
                tool_calls=0,
            )

        # Use rate limiter for real runs
        with self._rate_limiter:
            cmd = [
                "opencode", "run",
                "--format", "json",
                "--path", worktree_path,
                "--model", self.config.model,
                "--max-turns", str(self.config.max_steps),
            ] + self._build_tool_flags() + [task_description]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10-minute hard limit per run
            )

        duration = time.time() - start_time

        # Parse JSONL output for metrics
        input_tokens = 0
        output_tokens = 0
        tool_tokens = 0
        model_calls = 0
        tool_call_count = 0
        files_read = 0
        files_changed = 0
        patch_lines = 0
        errors = 0
        success = result.returncode == 0

        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                event_type = event.get("type", "")

                if event_type == "usage":
                    input_tokens += event.get("inputTokens", 0)
                    output_tokens += event.get("outputTokens", 0)
                    model_calls += 1

                elif event_type == "tool_call":
                    tool_call_count += 1
                    tool_name = event.get("tool", "")
                    tool_output = event.get("output", "")
                    tool_tokens += self._count_tokens(tool_output)

                    if tool_name in ("read", "read_all", "glob", "tree_sitter", "repo_map", "simple_rag"):
                        files_read += 1
                    elif tool_name in ("patch", "write"):
                        files_changed += 1
                        patch_lines += tool_output.count("\n")

                elif event_type == "error":
                    errors += 1

            except json.JSONDecodeError:
                # Non-JSON line (plain text log), count tokens as tool output
                tool_tokens += self._count_tokens(line)

        # Fallback: if OpenCode didn't emit structured usage, estimate from stdout
        if input_tokens == 0 and output_tokens == 0:
            input_tokens = self._count_tokens(task_description)
            output_tokens = self._count_tokens(result.stdout)

        return RunMetrics(
            success=success,
            eval_score=1.0 if success else 0.0,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tool_tokens=tool_tokens,
            duration_sec=duration,
            model_calls=model_calls,
            tool_calls=tool_call_count,
            files_read=files_read,
            files_changed=files_changed,
            patch_lines=patch_lines,
            errors=errors,
        )
```

---

## 5. Create `src/features/mcp_client.py`

**Purpose:** Async Python MCP client that connects to a locally running MCP server (Serena or Semble) via stdio.

```python
"""
Async MCP client for connecting to stdio-based MCP servers (Serena, Semble).
"""
import asyncio
import json
from typing import Any, Optional
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class McpToolClient:
    """
    Synchronous facade over async MCP ClientSession.
    Spawns the MCP server as a subprocess and communicates via stdio.
    """

    def __init__(self, server_command: str, server_args: list[str], cwd: Optional[str] = None):
        self.server_params = StdioServerParameters(
            command=server_command,
            args=server_args,
            cwd=cwd,
        )

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Synchronously call a tool on the MCP server and return result as string."""
        return asyncio.run(self._async_call_tool(tool_name, arguments))

    async def _async_call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        async with stdio_client(self.server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                # MCP results can be a list of content blocks
                if hasattr(result, "content") and result.content:
                    parts = []
                    for block in result.content:
                        if hasattr(block, "text"):
                            parts.append(block.text)
                        else:
                            parts.append(json.dumps(block.__dict__))
                    return "\n".join(parts)
                return str(result)

    def list_tools(self) -> list[str]:
        """Return list of tool names available on the server."""
        return asyncio.run(self._async_list_tools())

    async def _async_list_tools(self) -> list[str]:
        async with stdio_client(self.server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return [t.name for t in tools.tools]
```

---

## 6. Update `src/features/tool_registry/semantic_tools.py`

**Purpose:** Replace Serena/Semble stubs with real MCP clients using `McpToolClient`.

**Serena:** Connects to `serena` MCP server (`uvx --from serena mcp-server run .` or configured path).
**Semble:** Connects to `semble` MCP server (similar pattern).

**Updated SerenaAdapterTool.execute():**
```python
def execute(self, query: str) -> ToolResult:
    try:
        client = McpToolClient(
            server_command="uvx",
            server_args=["--from", "serena", "mcp-server", "run", self.worktree_path],
        )
        result = client.call_tool("find_symbol", {"query": query})
        return self.format_result(result)
    except Exception as e:
        # Fallback to BM25 if Serena is not installed
        return self.rag_engine.execute(query=query)
```

**Updated SembleAdapterTool.execute():**
```python
def execute(self, action: str = "map", query: str = "") -> ToolResult:
    try:
        client = McpToolClient(
            server_command="semble",
            server_args=["mcp", "--path", self.worktree_path],
        )
        tool_name = "get_symbols_overview" if action == "map" else "find_symbol"
        args = {"query": query} if query else {"path": self.worktree_path}
        result = client.call_tool(tool_name, args)
        return self.format_result(result)
    except Exception as e:
        # Fallback to BM25 if Semble is not installed
        return self.rag_engine.execute(query=action)
```

Both tools must import `McpToolClient` from `src.features.mcp_client`.

---

## 7. Create `src/features/tool_registry/lsp_tools.py`

**Purpose:** LSP-like symbol navigation using `jedi` (Python static analysis - no LSP server needed).

```python
"""
LSP-like symbols tool using jedi for Python static analysis.
Provides symbol lookup without requiring a running language server.
"""
import os
import jedi
from src.core.tools import BaseTool, ToolResult


class LspSymbolsTool(BaseTool):
    """Extracts symbols and references using jedi static analysis."""

    def __init__(self, worktree_path: str):
        super().__init__("lsp_symbols", "LSP-like symbol lookup using jedi static analysis")
        self.worktree_path = worktree_path

    def execute(self, symbol: str = "", file_path: str = "") -> ToolResult:
        results = []

        if file_path:
            # Get all symbols in a specific file
            full_path = os.path.join(self.worktree_path, file_path)
            if not os.path.isfile(full_path):
                return self.format_result(f"Error: File not found: {file_path}")
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    source = f.read()
                script = jedi.Script(source=source, path=full_path, project=jedi.Project(path=self.worktree_path))
                names = script.get_names(definitions=True)
                for n in names:
                    results.append(f"{n.type}: {n.name} (line {n.line}, col {n.column})")
            except Exception as e:
                return self.format_result(f"Error analyzing {file_path}: {e}")
        elif symbol:
            # Find all definitions of a symbol across the project
            for root, dirs, files in os.walk(self.worktree_path):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("venv", "__pycache__")]
                for fname in files:
                    if not fname.endswith(".py"):
                        continue
                    fpath = os.path.join(root, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            source = f.read()
                        script = jedi.Script(source=source, path=fpath, project=jedi.Project(path=self.worktree_path))
                        names = script.get_names(definitions=True)
                        for n in names:
                            if n.name == symbol:
                                rel = os.path.relpath(fpath, self.worktree_path)
                                results.append(f"{rel}: {n.type}: {n.name} (line {n.line})")
                    except Exception:
                        continue
        else:
            return self.format_result("Provide either 'symbol' or 'file_path' argument.")

        output = "\n".join(results) if results else "No symbols found."
        return self.format_result(output)
```

---

## 8. Create `src/features/tool_registry/shell_tool.py`

**Purpose:** Bash/shell tool for configs that include "shell" (e.g., claude_code_like).

```python
"""
Shell tool: executes arbitrary bash commands in the worktree context.
"""
import shlex
from src.core.tools import BaseTool, ToolResult
from src.features.shell import ShellExecutor


class ShellTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("shell", "Runs a bash command in the repository directory")
        self.worktree_path = worktree_path
        self.executor = ShellExecutor()

    def execute(self, command: str, timeout: float = 30.0) -> ToolResult:
        result = self.executor.run(command, cwd=self.worktree_path, timeout=timeout)
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        if not output.strip():
            output = f"(exit code: {result.exit_code})"
        return self.format_result(output)
```

---

## 9. Update `src/orchestrator/benchmark.py`

**Changes:**
1. Import and register `LspSymbolsTool` and `ShellTool` in `tool_map`
2. Fix the `EvalResult` constructor call — add `success=eval_res.success`
3. Remove unused imports (`RunMetrics`, `AgentConfig`)
4. Add `run_id` with timestamp format matching spec: `run_{timestamp}_{config.id}`

```python
# In _get_tools_for_config tool_map, add:
"lsp_symbols": LspSymbolsTool(worktree_path),
"shell": ShellTool(worktree_path),
```

Import additions at top:
```python
from src.features.tool_registry.lsp_tools import LspSymbolsTool
from src.features.tool_registry.shell_tool import ShellTool
```

Fix EvalResult call (line ~97-104):
```python
final_result = EvalResult(
    run_id=run_id,
    config_id=config.id,
    metrics=run_metrics,
    success=eval_res.success,  # now this field exists
    error=None,
    patch=None
)
```

---

## 10. Update `src/features/metrics_aggregator.py`

**Purpose:** Add `generate_rankings()` method that reads all run results and outputs a rankings table sorted by `success_per_token` (primary) and `total_tokens` (secondary).

```python
def generate_rankings(self) -> str:
    """
    Reads all metrics.json files from results directory and generates
    a markdown rankings table sorted by success_per_token descending.
    """
    import glob as glob_module
    rows = []
    for metrics_file in glob_module.glob(os.path.join(self.results_base_dir, "run_*", "metrics.json")):
        run_dir = os.path.dirname(metrics_file)
        run_name = os.path.basename(run_dir)
        with open(metrics_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        rows.append({
            "run": run_name,
            "success": data.get("success", False),
            "total_tokens": data.get("total_tokens", 0),
            "success_per_token": data.get("success_per_token", 0.0),
            "duration_sec": round(data.get("duration_sec", 0.0), 2),
            "model_calls": data.get("model_calls", 0),
            "tool_calls": data.get("tool_calls", 0),
            "cost_usd": round(data.get("cost_usd", 0.0), 6),
        })

    rows.sort(key=lambda r: (-r["success_per_token"], r["total_tokens"]))

    lines = [
        "# Benchmark Rankings",
        "",
        "| # | Run | Success | Total Tokens | Success/Token | Duration(s) | Model Calls | Tool Calls | Cost USD |",
        "|---|-----|---------|-------------|---------------|-------------|-------------|------------|----------|",
    ]
    for i, r in enumerate(rows, 1):
        ok = "✓" if r["success"] else "✗"
        lines.append(
            f"| {i} | {r['run']} | {ok} | {r['total_tokens']} | {r['success_per_token']:.6f} "
            f"| {r['duration_sec']} | {r['model_calls']} | {r['tool_calls']} | {r['cost_usd']} |"
        )

    output = "\n".join(lines)

    # Also save to file
    rankings_path = os.path.join(self.results_base_dir, "RANKINGS.md")
    with open(rankings_path, "w", encoding="utf-8") as f:
        f.write(output)

    return output
```

Also fix unused imports in this file: remove `import json` if not used elsewhere... actually json IS needed now. Remove `import yaml` (unused). Fix `from typing import Any, Dict` → remove if unused.

---

## 11. Update `src/orchestrator/benchmark.py` — call generate_rankings at end

After the suite loop completes, call `self.aggregator.generate_rankings()` and log the output.

```python
# After the for loop in run_suite():
rankings = self.aggregator.generate_rankings()
self.logger.info("Rankings generated:\n" + rankings)
```

---

## 12. Fix `tests/features/test_shell.py`

The 2 failing tests use `python` command which is not available in the WSL/venv context.
Fix to use the venv python explicitly or use a simpler cross-platform command:

```python
def test_shell_executor_success():
    executor = ShellExecutor()
    # Use 'echo' which is available on both Windows and Linux
    result = executor.run("echo hello_world")
    assert "hello_world" in result.stdout
    assert result.exit_code == 0

def test_shell_executor_timeout():
    executor = ShellExecutor()
    # 'sleep 2' available on Linux (WSL execution environment)
    cmd = "sleep 2"
    with pytest.raises(TimeoutError):
        executor.run(cmd, timeout=0.1)
```

---

## 13. Fix all 15 ruff lint errors

Remove unused imports across all files:
- `src/core/tools.py`: remove `Any` from typing import
- `src/features/agent_integration/opencode_runner.py`: will be replaced entirely
- `src/features/metrics_aggregator.py`: remove `json` (if not needed), `yaml`, `Any`, `Dict`
- `src/features/patch.py`: remove `subprocess`
- `src/features/tool_registry/basic_tools.py`: replace bare `except:` with `except Exception:`
- `src/features/tool_registry/semantic_tools.py`: remove `Tuple`, replace bare `except:` with `except Exception:`
- `src/orchestrator/benchmark.py`: remove `RunMetrics`, `AgentConfig` if unused

---

## 14. Update `main.py`

Fix the `--dry-run` help text (currently says "not implemented yet" - it IS implemented):
```python
parser.add_argument("--dry-run", action="store_true", 
    help="Run with mock agent (skips real API calls, uses simulated responses)")
```

Add `--worktree-base` argument to allow customizing worktree location.

After `orchestrator.run_suite(args.task)`, print the rankings table to stdout.

---

## Execution Order

1. Edit `pyproject.toml` — add/replace dependencies
2. Edit `src/core/models.py` — add fields + success_per_token
3. Edit `configs/benchmark_configs.yaml` — fix model versions
4. Replace `src/features/agent_integration/opencode_runner.py` — real OpenCode wrapper
5. Create `src/features/mcp_client.py` — MCP client
6. Update `src/features/tool_registry/semantic_tools.py` — real MCP adapters
7. Create `src/features/tool_registry/lsp_tools.py` — jedi-based LSP
8. Create `src/features/tool_registry/shell_tool.py` — shell tool
9. Update `src/orchestrator/benchmark.py` — wire new tools + fix EvalResult bug
10. Update `src/features/metrics_aggregator.py` — add generate_rankings()
11. Update `src/orchestrator/benchmark.py` (part 2) — call generate_rankings at end
12. Fix `tests/features/test_shell.py` — platform fix
13. Fix ruff lint across all files
14. Update `main.py` — dry-run help + print rankings
15. Run `pytest` and verify all tests pass

---

## Validation Criteria

- `pytest tests/ -v` → all tests pass (0 failures)
- `ruff check src/` → 0 errors
- `python main.py --repo . --task "test" --dry-run` runs without error and prints rankings
- All 20 configs have `gemini-2.5-flash`
- `EvalResult` has `success` field
- `RunMetrics` has all 14 spec metrics + `success_per_token`
- `LspSymbolsTool` and `ShellTool` registered in orchestrator
- `generate_rankings()` produces a markdown table
