# Plan: Fix Tool Reliability, Logging, and Smoke Tests

**Date**: 2026-05-25  
**Goal**: Fix 6 identified root causes of benchmark failures and add tool smoke-testing infrastructure.

---

## Root Causes Being Fixed

1. **Silent write sandbox block** (serena_only): `FileWriteTool._safe_path` returns None and the tool returns "Error: Access denied" string — Agno never sees `tool_call_error=True`, agent loops writing to blocked paths. `files_changed` counter is wrong (counts calls, not successes).
2. **Semgrep scans too broadly** (semgrep): no `--lang python` flag, scans all files/dirs, agent modifies 9 files.
3. **No agent conversation log**: post-mortem is blind — can't see what the agent decided to do and why.
4. **No git diff saved per run**: can't inspect what actually changed in the worktree.
5. **No tool smoke tests in preflight**: broken tools (wrong semgrep version, missing binary) pass `shutil.which` but fail at runtime.
6. **Jedi LSP path filtering**: `_search_symbol` may include stdlib/venv symbols on some platforms.

---

## Files to Create / Modify

### `src/features/tool_registry/basic_tools.py`
- `FileWriteTool.execute`: when `_safe_path` returns None, **raise** `PermissionError` instead of returning an error string. Agno will catch the exception and set `tool_call_error=True`, making the failure visible.
- Same for `FileReadTool.execute` on access denied.

### `src/features/agent_integration/agno_runner.py`
- `AgnoRunner.__init__`: accept optional `run_dir: str | None = None` parameter.
- `AgnoRunner.run`: add instruction item: `"Always use RELATIVE file paths (relative to the repository root) when calling file tools. Never use absolute paths."`
- `AgnoRunner.run`: add instruction item: `"If a tool returns an error, try a different approach — do not repeat the exact same tool call."`
- `_validate_run`: after computing diff, write `git diff HEAD` output to `os.path.join(self.run_dir, "changes.patch")` if `self.run_dir` is set.
- `run()`: accept `log_path: str | None = None` parameter. After agent.run() completes, serialize `response.messages` to JSON and write to `log_path`.
- Fix `files_changed` counter: only increment if `tool_exec.tool_call_error` is False AND the tool result string does NOT start with `"Error:"`. Check `getattr(tool_exec, 'result', '') or ''`.

### `src/features/tool_registry/grep_tools.py`
- `SemgrepTool.execute`: change command to:
  ```
  semgrep --lang python --pattern {safe_pattern} --json
  ```
  Then parse JSON output to extract `path`, `start.line`, `extra.lines` fields.
  If JSON parse fails, fall back to plain output.
  Add `--include="*.py"` flag (or pass `.` as target after flags).
  Full command: `semgrep --lang python --pattern {safe_pattern} --include '*.py' --quiet .`

### `src/features/tool_registry/lsp_tools.py`
- `LspSymbolsTool._search_symbol`: normalize paths using `os.path.realpath` before comparing with `self.worktree_path`. Ensure `os.path.realpath(self.worktree_path)` is stored once in `__init__` and used in comparisons.
- Also filter out results where `fpath` contains `.venv` or `site-packages`.

### `src/features/preflight.py`
- Add `_check_tool_smoke_tests()` method to `PreflightChecker`.
- Called after `_check_tool_cli_deps()`.
- Creates a temp dir with a tiny Python file (`test_smoke.py` containing `def hello(): pass`), then actually instantiates and calls each required tool:
  - `grep`: `GrepTool(tmp).execute("hello")` — assert "hello" in output
  - `rg`: `RgTool(tmp).execute("hello")` — assert "hello" in output
  - `git_grep`: init tmp git repo first, then test
  - `ugrep`: `UgrepTool(tmp).execute("hello")` — assert output not error
  - `semgrep`: `SemgrepTool(tmp).execute("def hello")` — assert no error prefix
  - `tree_sitter`: `TreeSitterTool(tmp).execute("test_smoke.py")` — assert "hello" in output
  - `lsp_symbols`: `LspSymbolsTool(tmp).execute(file_path="test_smoke.py")` — assert "hello" in output
- Each result: if `Error:` in output → add warning-level `PreflightResult` with detail.
- Level is `warning` (not critical) so benchmark still runs but operator sees which tools are broken.

### `src/orchestrator/benchmark.py`
- In `run_suite()` and `run_failed_configs()`: before calling `runner.run()`, compute `log_path = os.path.join(self.results_dir, run_id, "agent_messages.json")` and pass it to `runner.run(log_path=log_path)`.
- Pass `run_dir = os.path.join(self.results_dir, run_id)` to `AgnoRunner.__init__`.

### `tests/features/test_grep_tools.py`
- Import and add tests for `SemgrepTool` and `UgrepTool`.
- `test_semgrep_tool(temp_repo)`: skip if `not shutil.which("semgrep")`, create a Python file with a function, call `SemgrepTool(temp_repo).execute("def $FUNC(...)")`, assert file name in output.
- `test_ugrep_tool(temp_repo)`: skip if not installed, basic pattern search.
- `test_semgrep_tool_python_only(temp_repo)`: create a `.txt` file with matching text, verify semgrep does NOT return it (only scans `.py` files).

### `tests/features/test_lsp_tools.py`
- Add `test_lsp_symbols_no_stdlib_leakage(python_repo)`: call `execute(symbol="print")` (stdlib), assert the result is either "not found" or only contains worktree paths (no `site-packages`).

### `tests/features/test_basic_tools.py`
- Add `test_file_write_tool_access_denied(temp_workspace)`: attempt to write to an absolute path outside worktree (e.g. `/tmp/evil.txt`), assert that a `PermissionError` or error occurs (after the change to raise instead of return).

### New file: `tests/features/test_tool_smoke.py`
- Integration smoke tests that verify each tool works end-to-end in a real temp git repo.
- Tests are marked with `@pytest.mark.integration` so they can be run separately: `pytest -m integration`.
- Covers: grep, git_grep, rg, ugrep (if installed), semgrep (if installed), tree_sitter, repo_map, lsp_symbols, simple_rag, read, write, patch, glob.
- Each test: create minimal fixture → call tool → assert result contains expected content and no "Error:" prefix.

---

## Implementation Order

1. `basic_tools.py` — raise on sandbox violation
2. `grep_tools.py` — fix semgrep flags
3. `lsp_tools.py` — normalize paths
4. `agno_runner.py` — relative path instruction, logging, diff saving, counter fix
5. `benchmark.py` — pass log_path and run_dir
6. `preflight.py` — smoke test checks
7. Tests (all at once)

---

## Acceptance Criteria

- `uv run pytest tests/features/test_grep_tools.py` passes (semgrep/ugrep skipped if not installed)
- `uv run pytest tests/features/test_basic_tools.py` passes (write raises on access denied)
- `uv run pytest tests/features/test_tool_smoke.py -m integration` passes all installed tools
- After a benchmark run, each result dir contains: `metrics.json`, `agent_messages.json`, `changes.patch`
- PreflightChecker prints a smoke test warning for any broken tool before the run starts
