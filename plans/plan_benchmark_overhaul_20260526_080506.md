# Plan: Benchmark Infrastructure Overhaul
**Date:** 2026-05-26  
**Scope:** Tools, validation pipeline, benchmark robustness, logging, judge deferred evaluation

---

## Context

This is an agent benchmark framework (`tools_token_economy`) that runs a coding agent (Agno + gpt-4.1-mini) against 20 configs and measures token efficiency. The following critical issues were discovered during a live run and need to be fixed.

**Root cause analysis (from live run 20260526_003011):**
1. `patch` tool: 100% failure rate — LLMs generate patches without correct context, `git apply` rejects all of them. Agents fall back to `write` (full file overwrite).
2. `shell` tool: exists in code but NOT in any benchmark config. Agents can't self-verify via pytest.
3. Stale worktrees: 9 leftover worktrees from killed/crashed runs accumulate in `_oc_worktrees/`.
4. `_validate_run`: only runs CHANGED test files, never checks if existing tests were destroyed.
5. No cost guard: `03_gemini_like` ran 5 hours and cost $0.13 on a single config (now partially fixed by timeout, but no dollar cap).
6. LLM judge runs per-config, adding latency between configs. Should run once at end.
7. Agent instructions don't guide agents to use shell for self-verification.
8. No unified, per-tool validation pipeline — each tool has scattered check/install/verify scripts.

---

## Phase 1: Fix `patch` Tool — Multi-Strategy Application

### File: `src/features/patch.py`

Replace `PatchApplier.apply()` with a multi-strategy approach that tries multiple application methods and returns a detailed error if all fail.

```python
"""
Multi-strategy patch applicator.

Strategy order:
1. git apply --ignore-whitespace --whitespace=nowarn  (fast, tolerant of whitespace)
2. git apply --ignore-whitespace --recount            (recount lines, tolerate off-by-one)  
3. patch -p1 --ignore-whitespace --fuzz=3             (fuzzy, GNU patch)
4. Pure-additive fast-path: if patch has ONLY '+' lines (no '-' context deletions),
   extract additions and append to file directly.

On all failures, return a DETAILED error with the actual git apply output so the
agent knows exactly what went wrong.
"""
import os
import re
import shutil
import subprocess

from src.features.shell import ShellExecutor


class PatchApplier:
    def __init__(self, shell: ShellExecutor | None = None):
        self.shell = shell or ShellExecutor()

    def apply(self, worktree_path: str, patch_text: str) -> tuple[bool, str]:
        """
        Apply patch_text to worktree_path. Returns (success, error_detail).
        error_detail is empty string on success, helpful message on failure.
        """
        if not patch_text.strip():
            return True, ""

        patch_file = os.path.join(worktree_path, ".benchmark_patch")
        try:
            with open(patch_file, "w", encoding="utf-8") as f:
                f.write(patch_text)

            # Strategy 1: git apply --ignore-whitespace
            ok, err = self._try_git_apply(worktree_path, patch_file, ["--ignore-whitespace", "--whitespace=nowarn"])
            if ok:
                return True, ""

            # Strategy 2: git apply --ignore-whitespace --recount
            ok, err2 = self._try_git_apply(worktree_path, patch_file, ["--ignore-whitespace", "--recount"])
            if ok:
                return True, ""

            # Strategy 3: GNU patch -p1 --fuzz=3
            if shutil.which("patch"):
                ok, err3 = self._try_gnu_patch(worktree_path, patch_file)
                if ok:
                    return True, ""
            else:
                err3 = "GNU patch not available"

            # Strategy 4: pure-additive fast-path (append)
            ok, err4 = self._try_additive_append(worktree_path, patch_text)
            if ok:
                return True, ""

            # All failed — return combined error detail
            detail = (
                f"All patch strategies failed.\n"
                f"git apply: {err}\n"
                f"git apply --recount: {err2}\n"
                f"GNU patch: {err3}\n"
                f"Additive append: {err4}\n\n"
                f"HINT: Your patch has incorrect line numbers or context. "
                f"Use the 'read' tool to get exact file content, then generate a "
                f"correct unified diff with matching context lines. "
                f"Or use 'write' to write the complete file from scratch."
            )
            return False, detail

        finally:
            if os.path.exists(patch_file):
                os.remove(patch_file)

    def _try_git_apply(self, cwd: str, patch_file: str, extra_flags: list[str]) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["git", "apply"] + extra_flags + [patch_file],
                cwd=cwd, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return True, ""
            return False, (result.stderr or result.stdout).strip()[:300]
        except Exception as e:
            return False, str(e)

    def _try_gnu_patch(self, cwd: str, patch_file: str) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["patch", "-p1", "--ignore-whitespace", "--fuzz=3", "-i", patch_file],
                cwd=cwd, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return True, ""
            return False, (result.stderr or result.stdout).strip()[:300]
        except Exception as e:
            return False, str(e)

    def _try_additive_append(self, cwd: str, patch_text: str) -> tuple[bool, str]:
        """
        Fast-path for pure-additive patches: if patch only adds lines to one file,
        extract the additions and append them.
        """
        lines = patch_text.splitlines()
        
        # Find target file
        target_file = None
        additions = []
        has_deletions = False
        
        for line in lines:
            if line.startswith("+++ b/"):
                target_file = line[6:].strip()
            elif line.startswith("--- ") or line.startswith("+++ "):
                continue
            elif line.startswith("-") and not line.startswith("---"):
                has_deletions = True
                break
            elif line.startswith("+"):
                additions.append(line[1:])
        
        if has_deletions or not target_file or not additions:
            return False, "Patch has deletions or no target file — cannot use additive fast-path"
        
        full_path = os.path.join(cwd, target_file)
        if not os.path.isfile(full_path):
            return False, f"Target file not found: {target_file}"
        
        try:
            with open(full_path, "a", encoding="utf-8") as f:
                f.write("\n" + "\n".join(additions) + "\n")
            return True, ""
        except Exception as e:
            return False, str(e)
```

### File: `src/features/tool_registry/basic_tools.py` — Update PatchApplierTool

Update `PatchApplierTool.execute()` to use the new `(success, detail)` return value and surface the error detail to the agent:

```python
def execute(self, patch: str) -> ToolResult:
    success, error_detail = self.applier.apply(self.worktree_path, patch)
    if success:
        return self.format_result("Patch applied successfully.")
    else:
        return self.format_result(f"Error: Failed to apply patch.\n{error_detail}")
```

Also add a new **`InsertAfterTool`** — a safe additive-write tool that inserts content after a specific anchor line (for agents that want to add a function to a file without writing the whole thing):

```python
class InsertAfterTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__(
            "insert_after",
            "Inserts content after a specific line in an existing file. "
            "Use to ADD new functions/classes without overwriting existing content. "
            "anchor_pattern is a unique substring of the line after which to insert."
        )
        self.worktree_path = os.path.realpath(worktree_path)

    def execute(self, file_path: str, anchor_pattern: str, content: str) -> ToolResult:
        full_path = os.path.realpath(os.path.join(self.worktree_path, file_path))
        if not full_path.startswith(self.worktree_path + os.sep):
            raise PermissionError(f"Access denied: {file_path}")
        if not os.path.isfile(full_path):
            return self.format_result(f"Error: File not found: {file_path}")
        
        with open(full_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        # Find anchor line (last occurrence if multiple)
        anchor_idx = None
        for i in range(len(lines) - 1, -1, -1):
            if anchor_pattern in lines[i]:
                anchor_idx = i
                break
        
        if anchor_idx is None:
            # Fall back to append if anchor not found
            with open(full_path, "a", encoding="utf-8") as f:
                f.write("\n" + content + "\n")
            return self.format_result(f"Anchor '{anchor_pattern}' not found — content appended to end of {file_path}")
        
        # Insert after anchor
        insertion = "\n" + content + "\n"
        new_lines = lines[:anchor_idx + 1] + [insertion] + lines[anchor_idx + 1:]
        with open(full_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        return self.format_result(f"Content inserted after line {anchor_idx + 1} in {file_path}")
```

### File: `tests/features/test_patch.py` — Extend with multi-strategy tests

Add tests:
1. `test_apply_malformed_hunk_falls_back_to_strategy2` — patch with wrong line numbers, strategy 1 fails, strategy 2 succeeds
2. `test_apply_additive_only_fast_path` — patch with only `+` lines succeeds via fast-path
3. `test_apply_all_fail_returns_helpful_error` — truly malformed patch returns error with "HINT:"
4. `test_patch_applier_tool_surfaces_error_to_agent` — PatchApplierTool wraps error in ToolResult

---

## Phase 2: Shell Tool as Universal Base Tool

### File: `src/orchestrator/benchmark.py` — `_get_tools_for_config`

Add `shell` as an **always-available base tool** regardless of config:

```python
def _get_tools_for_config(self, config: Any, worktree_path: str) -> list[Any]:
    tool_map = { ... }  # existing map unchanged
    
    tools = [tool_map[t] for t in config.tools if t in tool_map]
    
    # Shell is always available as a base tool for self-verification
    # even if not listed in config.tools
    if "shell" not in config.tools:
        tools.append(ShellTool(worktree_path))
    
    return tools
```

### File: `src/features/tool_registry/shell_tool.py` — Improve description

Update `ShellTool` description and add a `run_tests` convenience wrapper:

```python
class ShellTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__(
            "shell",
            "Runs a bash command in the repository. "
            "IMPORTANT: Use this to verify your changes BEFORE saying TASK_COMPLETE. "
            "Example: shell('uv run --extra dev pytest tests/unit/test_api_google_oauth.py::test_google_redirect_includes_required_scopes -xvs') "
            "to verify your new test passes."
        )
        self.worktree_path = worktree_path
        self.executor = ShellExecutor()

    def execute(self, command: str, timeout: float = 60.0) -> ToolResult:
        # Inject eval venv env var to avoid destroying benchmark venv
        import os
        env = {k: v for k, v in os.environ.items() if k != 'UV_PROJECT_ENVIRONMENT'}
        env['UV_PROJECT_ENVIRONMENT'] = os.path.join(self.worktree_path, '.eval_venv')
        result = self.executor.run(command, cwd=self.worktree_path, timeout=timeout, env=env)
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        if not output.strip():
            output = f"(exit code: {result.exit_code})"
        return self.format_result(output)
```

Note: update `ShellExecutor.run()` signature in `src/features/shell.py` to accept optional `env: dict | None = None` parameter and pass it to `subprocess.run`.

### File: `src/features/agent_integration/agno_runner.py` — Better agent instructions

Update the `instructions` list in both `_run_with_mcp()` and the sync `run()` path:

```python
instructions=[
    f"You are a coding agent working in the repository at: {worktree_path}",
    "Complete the task using only the tools provided.",
    "Always use RELATIVE file paths (relative to the repository root).",
    
    # Patch vs write guidance
    "PREFERRED: Use 'patch' to modify existing files with a unified diff. "
    "Include 3 lines of context before and after the change. "
    "Format: '--- a/path/to/file\\n+++ b/path/to/file\\n@@ -LINE,COUNT +LINE,COUNT @@\\n context\\n+addition\\n context'",
    "ALTERNATIVE: If patch fails repeatedly, use 'insert_after' to append a new function "
    "after an anchor line without overwriting existing content.",
    "LAST RESORT: Use 'write' only when creating a NEW file that does not yet exist. "
    "Do NOT use 'write' on existing files — it overwrites all existing content.",
    
    # Self-verification
    "MANDATORY VERIFICATION: After any file modification, use 'shell' to run the specific "
    "test function: shell('uv run --extra dev pytest <test_file>::<test_name> -xvs') "
    "If the test fails, read the error and fix it before trying again.",
    "Never output TASK_COMPLETE until the shell verification confirms the test passes.",
    
    "If a tool returns an error, try a different approach — do not repeat the exact same call.",
],
```

### File: `configs/benchmark_configs.yaml` — Document shell availability

Add a comment noting that `shell` is always available as a base tool. Do NOT add `shell` to each config's tools list (it's injected automatically), but document this behavior.

### File: `src/features/preflight.py` — Add shell smoke test

Add shell tool to `_check_tool_smoke_tests`:
```python
"shell": (ShellTool, "echo hello"),
```
Verify the ShellTool executes correctly and returns output.

Also add to `_TOOL_CLI_DEPS`:
```python
"insert_after": None,  # pure-Python, no CLI
```

### File: `tests/features/test_shell_tool.py` — Extend

Add tests for:
1. `test_shell_tool_injects_eval_venv_env_var` — UV_PROJECT_ENVIRONMENT is set correctly
2. `test_shell_tool_available_even_without_config_tools` — shell present even if not in config.tools (test via orchestrator mock)

---

## Phase 3: Stale Worktree Cleanup

### File: `src/features/isolation.py` — Add cleanup_stale()

```python
def cleanup_stale(self) -> list[str]:
    """
    Finds and removes all worktrees in worktree_base that are not in active_worktrees.
    Also runs 'git worktree prune' to clean up git's internal tracking.
    Returns list of cleaned-up paths.
    """
    cleaned = []
    
    # First prune git's internal records
    subprocess.run(
        [self.git_cmd, "worktree", "prune"],
        cwd=self.repo_path, capture_output=True
    )
    
    if not os.path.isdir(self.worktree_base):
        return cleaned
    
    for entry in os.scandir(self.worktree_base):
        if not entry.is_dir():
            continue
        run_id = entry.name
        if run_id in self.active_worktrees:
            continue  # still active
        
        # Remove stale worktree
        wt_path = entry.path
        try:
            subprocess.run(
                [self.git_cmd, "worktree", "remove", "--force", wt_path],
                cwd=self.repo_path, capture_output=True
            )
        except Exception:
            pass
        
        if os.path.exists(wt_path):
            shutil.rmtree(wt_path, ignore_errors=True)
        cleaned.append(wt_path)
    
    return cleaned
```

### File: `src/orchestrator/benchmark.py` — Call cleanup_stale at startup

In `run_suite()`, after preflight, before iterating configs:
```python
stale = self.isolation.cleanup_stale()
if stale:
    self.logger.info("Cleaned up %d stale worktrees: %s", len(stale), stale)
```

### File: `tests/features/test_isolation.py` — Add cleanup tests

Add:
1. `test_cleanup_stale_removes_orphaned_worktrees` — create worktrees manually, call cleanup, verify they're gone
2. `test_cleanup_stale_preserves_active_worktrees` — active worktree not removed

---

## Phase 4: Fix `_validate_run` — Detect Destroyed Tests

### File: `src/features/agent_integration/agno_runner.py` — Update `_validate_run`

Add detection of deleted test functions:

```python
def _validate_run(self, worktree_path: str, test_cmd: str) -> tuple[bool, int, int]:
    # ... existing git status detection ...
    
    # NEW: detect if agent deleted existing test functions
    diff_result = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=worktree_path, capture_output=True, text=True
    )
    
    # Count deleted test function definitions
    deleted_test_fns = [
        line for line in diff_result.stdout.splitlines()
        if line.startswith("-") and not line.startswith("---")
        and re.search(r"^\-\s*(async\s+)?def\s+test_", line)
    ]
    
    if deleted_test_fns:
        _log.warning(
            "Agent deleted %d existing test function(s): %s. Marking as FAIL.",
            len(deleted_test_fns),
            [l.strip() for l in deleted_test_fns[:5]]
        )
        return False, 0, patch_lines
    
    # ... rest of existing logic unchanged ...
```

Add `import re` at the top of `agno_runner.py` if not already present.

### File: `tests/features/test_agno_runner_validation.py` — Add test

Add:
1. `test_validate_run_fails_when_agent_deletes_test_functions` — mock diff shows deleted `def test_foo`, verify `_validate_run` returns False

---

## Phase 5: Cost Guard & Token Budget

### File: `src/features/cost_guard.py` — NEW

```python
"""
CostGuard: accumulates per-run costs and enforces a per-suite budget.
"""
from __future__ import annotations
import logging

_log = logging.getLogger(__name__)


class BudgetExceededError(RuntimeError):
    pass


class CostGuard:
    def __init__(self, max_cost_usd: float = 5.0, max_tokens_per_config: int = 500_000):
        self.max_cost_usd = max_cost_usd
        self.max_tokens_per_config = max_tokens_per_config
        self.accumulated_cost: float = 0.0
        self.config_costs: dict[str, float] = {}

    def check_before_run(self, config_id: str) -> None:
        """Call before starting a config run. Raises BudgetExceededError if over budget."""
        if self.accumulated_cost >= self.max_cost_usd:
            raise BudgetExceededError(
                f"Suite budget exceeded: ${self.accumulated_cost:.4f} >= ${self.max_cost_usd:.4f}. "
                f"Stopping before {config_id}."
            )

    def record(self, config_id: str, cost_usd: float, total_tokens: int) -> None:
        """Record cost after a config run. Warns if per-config token budget exceeded."""
        self.accumulated_cost += cost_usd
        self.config_costs[config_id] = cost_usd
        
        if total_tokens > self.max_tokens_per_config:
            _log.warning(
                "Config %s used %d tokens (budget: %d) — consider reducing max_steps or adding timeout.",
                config_id, total_tokens, self.max_tokens_per_config
            )
        
        _log.info(
            "Cost so far: $%.4f / $%.4f budget (%s: $%.4f)",
            self.accumulated_cost, self.max_cost_usd, config_id, cost_usd
        )

    @property
    def remaining_budget(self) -> float:
        return max(0.0, self.max_cost_usd - self.accumulated_cost)
```

### File: `src/orchestrator/benchmark.py` — Integrate CostGuard

1. Add `max_cost_usd: float = 5.0` parameter to `BenchmarkOrchestrator.__init__`
2. Instantiate `self.cost_guard = CostGuard(max_cost_usd=max_cost_usd)`
3. In the config loop:
   ```python
   try:
       self.cost_guard.check_before_run(config.id)
   except BudgetExceededError as e:
       self.logger.error(str(e))
       break
   
   # ... run config ...
   
   self.cost_guard.record(config.id, run_metrics.cost_usd, run_metrics.total_tokens)
   ```
4. Add `--max-cost` CLI arg in `main.py` (default 5.0), pass to `BenchmarkOrchestrator`

### File: `configs/benchmark_configs.yaml` — Add budget settings

Under `benchmark:` section add:
```yaml
  max_cost_usd: 5.0
  max_tokens_per_config: 500000
```

### File: `src/core/config_loader.py` — Expose new fields

Add `max_cost_usd: float = 5.0` and `max_tokens_per_config: int = 500000` to `BenchmarkMeta`.

### File: `tests/features/test_cost_guard.py` — NEW

Tests:
1. `test_cost_guard_raises_when_over_budget`
2. `test_cost_guard_accumulates_correctly`
3. `test_cost_guard_warns_on_token_runaway`

---

## Phase 6: Deferred LLM Judge (Evaluate at Suite End)

### File: `src/features/llm_judge.py` — Add batch_evaluate

```python
def batch_evaluate(self, items: list[dict]) -> list[JudgeReport]:
    """
    Evaluate multiple runs at once. items: list of dicts with keys:
    task_description, agent_messages, patch, config_tools, tests_passed, tests_total, success
    Returns list of JudgeReport in same order.
    """
    return [self.evaluate(**item) for item in items]
```

### File: `src/orchestrator/benchmark.py` — Defer judge to suite end

1. During config loop: save run WITHOUT judge scores (raw metrics only)
2. Collect `_pending_judge_items: list[dict]` with config_id + all judge inputs
3. After the config loop completes, run `judge.batch_evaluate(pending_items)` 
4. Update each run's `metrics.json` with the judge scores

```python
# At end of run_suite(), after all configs:
if not self.dry_run and pending_judge_items:
    self.logger.info("Running LLM judge on %d completed runs...", len(pending_judge_items))
    judge = LLMJudge()
    for item in pending_judge_items:
        try:
            report = judge.evaluate(**item['judge_kwargs'])
            # Reload and update metrics.json
            metrics_path = os.path.join(self.aggregator.results_base_dir, item['run_id'], 'metrics.json')
            with open(metrics_path) as f:
                data = json.load(f)
            data.update({
                'task_solved_score': report.task_solved_score,
                'tool_correctness_score': report.tool_correctness_score,
                'judge_reasoning_task': report.task_solved_reasoning,
                'judge_reasoning_tools': report.tool_correctness_reasoning,
                'judge_model': report.judge_model,
            })
            with open(metrics_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.logger.warning("Judge failed for %s: %s", item['run_id'], e)
```

---

## Phase 7: Comprehensive Per-Tool Validation Pipeline

### New directory: `src/features/tool_registry/validators/`

Create the following files:

#### `src/features/tool_registry/validators/__init__.py`
Empty or re-export `BaseToolValidator`.

#### `src/features/tool_registry/validators/_base.py`

```python
"""BaseToolValidator — standard interface for per-tool validation."""
from __future__ import annotations
import abc
import logging
import os
import subprocess
import tempfile

_log = logging.getLogger(__name__)


class ValidationResult:
    def __init__(self, name: str, passed: bool, detail: str = ""):
        self.name = name
        self.passed = passed
        self.detail = detail

    def __repr__(self):
        s = "PASS" if self.passed else "FAIL"
        return f"[{s}] {self.name}: {self.detail}"


class BaseToolValidator(abc.ABC):
    """
    Universal connector interface for per-tool validation.
    Every tool must implement this to participate in the validation pipeline.
    """
    
    @property
    @abc.abstractmethod
    def tool_name(self) -> str:
        """Identifier matching the key in benchmark_configs.yaml tools: list."""

    @property
    def cli_binary(self) -> str | None:
        """Name of the CLI binary required (None if pure-Python)."""
        return None

    @property
    def is_expensive(self) -> bool:
        """True if prepare() does significant work (RAG indexing, model download)."""
        return False

    def check_installed(self) -> ValidationResult:
        """Check if binary/package is available."""
        if self.cli_binary is None:
            return ValidationResult(f"{self.tool_name}:installed", True, "pure-Python, no CLI needed")
        import shutil
        found = shutil.which(self.cli_binary) is not None
        return ValidationResult(
            f"{self.tool_name}:installed",
            found,
            f"Found at {shutil.which(self.cli_binary)}" if found else f"'{self.cli_binary}' not in PATH"
        )

    def install(self) -> ValidationResult:
        """Attempt to install the tool. Override in subclasses."""
        return ValidationResult(f"{self.tool_name}:install", False, "No install handler defined")

    @abc.abstractmethod
    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        """Quick functional test using a temp directory with a tiny Python file."""

    def validate_with_agno(self, tmp_dir: str) -> ValidationResult:
        """
        Verify that Agno agent can call this tool.
        Default: instantiate the tool class, call execute with a test arg,
        verify no exception and non-empty output.
        """
        return ValidationResult(f"{self.tool_name}:agno_visibility", True, "default: not tested")

    def prepare(self, repo_path: str) -> ValidationResult:
        """
        Expensive one-time preparation (RAG index build, repo map generation).
        Should be idempotent — check if already done before running.
        """
        return ValidationResult(f"{self.tool_name}:prepare", True, "no preparation needed")

    def _make_smoke_repo(self, tmp_dir: str) -> str:
        """Helper: create a minimal git repo with one Python file for smoke tests."""
        test_file = os.path.join(tmp_dir, "test_smoke.py")
        with open(test_file, "w") as f:
            f.write("def hello_world():\n    return 42\n\nresult = hello_world()\n")
        subprocess.run(["git", "init", "-q"], cwd=tmp_dir)
        subprocess.run(["git", "add", "test_smoke.py"], cwd=tmp_dir)
        subprocess.run(["git", "config", "user.email", "smoke@test.com"], cwd=tmp_dir)
        subprocess.run(["git", "config", "user.name", "Smoke"], cwd=tmp_dir)
        subprocess.run(["git", "commit", "-m", "init", "-q"], cwd=tmp_dir)
        return tmp_dir
```

#### `src/features/tool_registry/validators/basic_validators.py`

Validators for: `read`, `write`, `patch`, `insert_after`, `glob`, `shell`.

Each validator's `smoke_test`:
- `read`: instantiate `FileReadTool`, call `execute("test_smoke.py")`, check output contains "hello_world"
- `write`: write a new file, verify it exists on disk
- `patch`: apply a valid additive patch using the multi-strategy applier, verify success
- `insert_after`: insert a new function after anchor, verify file contains insertion
- `glob`: glob for `*.py`, verify result contains test_smoke.py
- `shell`: run `echo smoke_test`, verify output contains "smoke_test"

`validate_with_agno` for shell:
- Build a tiny Agno agent with ShellTool, ask it to run `echo agno_ok`, verify response contains `agno_ok`

#### `src/features/tool_registry/validators/grep_validators.py`

Validators for: `grep`, `rg`, `git_grep`, `ugrep`, `ast_grep`.

Each `smoke_test` searches for `hello_world` in `test_smoke.py` and verifies the match is found.

`ast_grep` smoke test: search for pattern `def $NAME()` and verify it finds `hello_world`.

#### `src/features/tool_registry/validators/structural_validators.py`

Validators for: `tree_sitter`, `lsp_symbols`, `repo_map`.

- `tree_sitter` smoke: extract symbols from `test_smoke.py`, verify `hello_world` in output
- `lsp_symbols` smoke: same
- `repo_map` smoke: generate repo map for tmp_dir, verify output non-empty and contains `test_smoke.py`

#### `src/features/tool_registry/validators/semantic_validators.py`

Validator for `simple_rag`. Mark as `is_expensive = True`.

```python
class SimpleRagValidator(BaseToolValidator):
    tool_name = "simple_rag"
    is_expensive = True
    
    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        # Small test: build RAG on tmp_dir with one file, query for "hello_world"
        from src.features.tool_registry.semantic_tools import SimpleRagTool
        try:
            tool = SimpleRagTool(tmp_dir)
            tool.ingest()
            result = tool.execute(query="hello_world")
            passed = "hello_world" in str(result.output)
            return ValidationResult("simple_rag:smoke", passed, str(result.output)[:100])
        except Exception as e:
            return ValidationResult("simple_rag:smoke", False, str(e))
    
    def prepare(self, repo_path: str) -> ValidationResult:
        """Build the RAG index for the target repo."""
        from src.features.tool_registry.semantic_tools import SimpleRagTool
        cache_marker = os.path.join(repo_path, ".rag_index_ready")
        if os.path.exists(cache_marker):
            return ValidationResult("simple_rag:prepare", True, "RAG index already built (cached)")
        try:
            tool = SimpleRagTool(repo_path)
            tool.ingest()
            with open(cache_marker, "w") as f:
                f.write("ready")
            return ValidationResult("simple_rag:prepare", True, "RAG index built successfully")
        except Exception as e:
            return ValidationResult("simple_rag:prepare", False, str(e))
```

#### `src/features/tool_registry/validators/mcp_validators.py`

Validators for: `serena`, `semble`.

Both use the existing verify scripts as their `smoke_test` logic (adapted to the interface).

`validate_with_agno` for serena:
- Start serena MCP server
- Create an MCPTools instance
- Initialize it
- Verify it exposes >= 20 tools
- Shut down

### New file: `src/features/validation_pipeline.py`

```python
"""
ValidationPipeline: orchestrates per-tool validators.

Usage:
    pipeline = ValidationPipeline(repo_path="/path/to/repo", tool_names=["rg", "read", "shell"])
    report = pipeline.run(install_missing=True, run_expensive=True)
    report.print_summary()
    if not report.all_passed:
        sys.exit(1)
"""
from __future__ import annotations
import logging
import tempfile
from dataclasses import dataclass, field

from src.features.tool_registry.validators._base import BaseToolValidator, ValidationResult

_log = logging.getLogger(__name__)


@dataclass
class PipelineReport:
    results: list[ValidationResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failed(self) -> list[ValidationResult]:
        return [r for r in self.results if not r.passed]

    def print_summary(self) -> None:
        print("\n" + "=" * 60)
        print("  VALIDATION PIPELINE REPORT")
        print("=" * 60)
        for r in self.results:
            tag = "[PASS]" if r.passed else "[FAIL]"
            print(f"  {tag:<8} {r.name}: {r.detail}")
        print("=" * 60)
        if self.all_passed:
            print("  All validators passed.")
        else:
            print(f"  {len(self.failed)} validator(s) FAILED.")
        print("=" * 60 + "\n")


# Registry of all validators, keyed by tool_name
_VALIDATOR_REGISTRY: dict[str, BaseToolValidator] = {}

def _register_validators():
    """Lazily import and register all validators."""
    if _VALIDATOR_REGISTRY:
        return
    from src.features.tool_registry.validators.basic_validators import (
        ReadValidator, WriteValidator, PatchValidator, InsertAfterValidator, GlobValidator, ShellValidator
    )
    from src.features.tool_registry.validators.grep_validators import (
        GrepValidator, RgValidator, GitGrepValidator, UgrepValidator, AstGrepValidator
    )
    from src.features.tool_registry.validators.structural_validators import (
        TreeSitterValidator, LspValidator, RepoMapValidator
    )
    from src.features.tool_registry.validators.semantic_validators import SimpleRagValidator
    from src.features.tool_registry.validators.mcp_validators import SerenaValidator, SembleValidator
    
    for v in [
        ReadValidator(), WriteValidator(), PatchValidator(), InsertAfterValidator(),
        GlobValidator(), ShellValidator(),
        GrepValidator(), RgValidator(), GitGrepValidator(), UgrepValidator(), AstGrepValidator(),
        TreeSitterValidator(), LspValidator(), RepoMapValidator(),
        SimpleRagValidator(),
        SerenaValidator(), SembleValidator(),
    ]:
        _VALIDATOR_REGISTRY[v.tool_name] = v


class ValidationPipeline:
    def __init__(
        self,
        repo_path: str,
        tool_names: list[str],
        install_missing: bool = True,
        run_expensive: bool = True,
    ):
        self.repo_path = repo_path
        self.tool_names = tool_names
        self.install_missing = install_missing
        self.run_expensive = run_expensive
        _register_validators()

    def run(self) -> PipelineReport:
        report = PipelineReport()
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            for tool_name in self.tool_names:
                validator = _VALIDATOR_REGISTRY.get(tool_name)
                if validator is None:
                    report.results.append(ValidationResult(f"{tool_name}:registry", True, "no validator registered — skipped"))
                    continue
                
                # Step 1: Check installed
                result = validator.check_installed()
                report.results.append(result)
                
                # Step 2: If not installed and install_missing, try install
                if not result.passed and self.install_missing:
                    install_result = validator.install()
                    report.results.append(install_result)
                    if not install_result.passed:
                        continue  # can't validate further
                    # Re-check
                    result = validator.check_installed()
                    if not result.passed:
                        report.results.append(ValidationResult(f"{tool_name}:installed_after_install", False, "still not found"))
                        continue
                
                if not result.passed:
                    continue  # skip further checks if not installed
                
                # Step 3: Smoke test
                self._make_smoke_repo(tmp_dir)
                smoke = validator.smoke_test(tmp_dir)
                report.results.append(smoke)
                
                # Step 4: Agno visibility
                agno = validator.validate_with_agno(tmp_dir)
                report.results.append(agno)
                
                # Step 5: Expensive prep (if applicable)
                if validator.is_expensive and self.run_expensive:
                    prep = validator.prepare(self.repo_path)
                    report.results.append(prep)
        
        return report

    def _make_smoke_repo(self, tmp_dir: str) -> None:
        """Ensure tmp_dir is a valid git repo with test_smoke.py."""
        import os, subprocess
        test_file = os.path.join(tmp_dir, "test_smoke.py")
        if not os.path.exists(test_file):
            with open(test_file, "w") as f:
                f.write("def hello_world():\n    return 42\n")
            if not os.path.exists(os.path.join(tmp_dir, ".git")):
                subprocess.run(["git", "init", "-q"], cwd=tmp_dir)
                subprocess.run(["git", "add", "test_smoke.py"], cwd=tmp_dir)
                subprocess.run(["git", "config", "user.email", "smoke@test"], cwd=tmp_dir)
                subprocess.run(["git", "config", "user.name", "Smoke"], cwd=tmp_dir)
                subprocess.run(["git", "commit", "-m", "init", "-q"], cwd=tmp_dir)
```

### New file: `scripts/validate_pipeline.py` — CLI entry point

```python
#!/usr/bin/env python3
"""
Run the full validation pipeline for all tools required by benchmark configs.

Usage:
    python scripts/validate_pipeline.py                    # validate all tools
    python scripts/validate_pipeline.py --tools rg grep    # validate specific tools
    python scripts/validate_pipeline.py --no-expensive     # skip RAG/repo-map prep
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.core.config_loader import load_benchmark_meta
from src.features.validation_pipeline import ValidationPipeline


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--configs", default="configs/benchmark_configs.yaml")
    parser.add_argument("--tools", nargs="+", help="Specific tools to validate")
    parser.add_argument("--no-expensive", action="store_true")
    parser.add_argument("--no-install", action="store_true")
    args = parser.parse_args()

    meta = load_benchmark_meta(args.configs)
    
    if args.tools:
        tool_names = args.tools
    else:
        # Collect all unique tools from all configs
        from src.core.config_loader import load_configs
        configs = load_configs(args.configs)
        tool_names = sorted({t for c in configs for t in c.tools})
        tool_names.append("shell")  # always validate shell
    
    pipeline = ValidationPipeline(
        repo_path=meta.repo,
        tool_names=tool_names,
        install_missing=not args.no_install,
        run_expensive=not args.no_expensive,
    )
    report = pipeline.run()
    report.print_summary()
    sys.exit(0 if report.all_passed else 1)


if __name__ == "__main__":
    main()
```

### Update `scripts/setup_benchmark.sh` — Call validation pipeline

After the existing checks, add:
```bash
echo ""
echo "=== [4/3] Full validation pipeline ==="
$VENV_PYTHON scripts/validate_pipeline.py --no-expensive
```

---

## Phase 8: Improved Run Logging

### File: `src/orchestrator/benchmark.py` — Run timeline logging

In the config run loop, write a `run_events.jsonl` file (newline-delimited JSON) with timestamped events:

```python
import time

class RunEventLogger:
    def __init__(self, run_dir: str):
        self.path = os.path.join(run_dir, "run_events.jsonl")
        self._start = time.time()
    
    def log(self, event_type: str, **data):
        import json
        entry = {"t": round(time.time() - self._start, 3), "event": event_type, **data}
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
```

Log events:
- `run_start`: config_id, model, tools, worktree_path
- `tool_call`: tool_name, args_summary (first 100 chars), result_summary, duration_ms
- `patch_applied` / `patch_failed`: file_path, lines_added, lines_removed
- `test_run`: command, outcome, tests_passed, duration_ms
- `run_end`: success, total_tokens, cost_usd, duration_sec

Also update `MetricsAggregator.save_run()` to write a `file_changes.json`:

```json
{
  "files_modified": ["tests/unit/test_api_google_oauth.py"],
  "test_functions_added": ["test_google_redirect_includes_required_scopes"],
  "test_functions_deleted": [],
  "lines_added": 12,
  "lines_removed": 0
}
```

Generate this from parsing `final.patch` if it exists.

---

## Phase 9: Fix `prompt_builder.py` Test Name Inconsistency

### File: `tests/features/test_prompt_builder.py`

Rename `test_build_tool_restriction_prefix_empty_for_no_retrieval_tools` → `test_build_tool_restriction_prefix_includes_write_tools_even_without_retrieval_tools` to match the actual assertion (prefix is NOT empty, contains write tools section).

---

## Summary of Files to Create

| File | Purpose |
|------|---------|
| `src/features/cost_guard.py` | Cost/token budget enforcement |
| `src/features/validation_pipeline.py` | Per-tool validation orchestrator |
| `src/features/tool_registry/validators/__init__.py` | Package init |
| `src/features/tool_registry/validators/_base.py` | BaseToolValidator ABC |
| `src/features/tool_registry/validators/basic_validators.py` | read/write/patch/shell validators |
| `src/features/tool_registry/validators/grep_validators.py` | grep family validators |
| `src/features/tool_registry/validators/structural_validators.py` | tree_sitter/lsp/repo_map |
| `src/features/tool_registry/validators/semantic_validators.py` | simple_rag (expensive) |
| `src/features/tool_registry/validators/mcp_validators.py` | serena/semble MCP validators |
| `scripts/validate_pipeline.py` | CLI entry for validation pipeline |
| `tests/features/test_cost_guard.py` | CostGuard tests |
| `tests/features/test_validation_pipeline.py` | ValidationPipeline tests |

## Summary of Files to Modify

| File | Change |
|------|--------|
| `src/features/patch.py` | Multi-strategy apply, detailed error messages |
| `src/features/tool_registry/basic_tools.py` | InsertAfterTool + PatchApplierTool error surfacing |
| `src/features/tool_registry/shell_tool.py` | Better description, eval_venv env injection |
| `src/features/isolation.py` | cleanup_stale() method |
| `src/features/preflight.py` | Add shell smoke test, InsertAfter CLI dep |
| `src/features/agent_integration/agno_runner.py` | Better instructions (patch>write, shell verify), detect deleted tests |
| `src/features/llm_judge.py` | batch_evaluate() method |
| `src/orchestrator/benchmark.py` | Shell always-available, stale cleanup, cost guard, deferred judge, event logging |
| `src/core/models.py` | Add max_cost_usd/max_tokens_per_config to BenchmarkMeta |
| `src/core/config_loader.py` | Expose new BenchmarkMeta fields |
| `configs/benchmark_configs.yaml` | Add max_cost_usd/max_tokens_per_config settings |
| `scripts/setup_benchmark.sh` | Call validate_pipeline.py |
| `tests/features/test_patch.py` | Multi-strategy tests |
| `tests/features/test_isolation.py` | cleanup_stale tests |
| `tests/features/test_prompt_builder.py` | Rename inconsistent test |
| `tests/features/test_shell_tool.py` | Extend with eval_venv test |
| `tests/features/test_agno_runner_validation.py` | Add deleted-test detection test |
| `main.py` | Add --max-cost CLI arg |

## Implementation Order

1. Phase 1 (patch fix) — most impactful on pass rate
2. Phase 3 (stale worktree cleanup) — quick, prevents accumulation
3. Phase 2 (shell always-available + better instructions) — self-verification
4. Phase 4 (detect deleted tests) — honest metrics
5. Phase 5 (cost guard) — protection
6. Phase 6 (deferred judge) — efficiency
7. Phase 7 (validation pipeline) — infrastructure
8. Phase 8 (event logging) — observability
9. Phase 9 (test name fix) — housekeeping

## Verification

After all changes, run:
```bash
UV_LINK_MODE=copy uv run pytest tests/ -q --tb=short
```
All existing 116 tests must still pass (plus the new ones). Target: 130+ tests passing.

Then run:
```bash
python scripts/validate_pipeline.py --no-expensive
```
All validators should pass.
