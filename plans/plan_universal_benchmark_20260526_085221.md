# Plan: Universal Agent Benchmark Infrastructure Overhaul
**Date:** 2026-05-26
**Author:** Plan

---

## Context

This is a coding-agent benchmark framework (`tools_token_economy`). It runs an Agno-based LLM agent (gpt-4.1-mini) against 20 tool configurations and evaluates how well different tool combinations help solve a coding task in an arbitrary target codebase.

**KEY REQUIREMENT: The benchmark must be fully universal. The task can be ANYTHING — add a function, fix a bug, refactor, write documentation, etc. The target codebase may or may not have tests. Success cannot be defined purely by test results.**

### Current state of unstaged changes (already in working tree, not committed):
- `src/features/patch.py` — multi-strategy PatchApplier (new signature: returns `tuple[bool, str]`)
- `src/features/tool_registry/basic_tools.py` — `InsertAfterTool` added, `PatchApplierTool` uses new tuple API
- `src/features/agent_integration/agno_runner.py` — timeout enforcement via asyncio.wait_for + ThreadPoolExecutor
- `src/features/prompt_builder.py` — minor updates
- `tests/features/test_prompt_builder.py` — test updates

**Two bugs in current unstaged state that MUST be fixed first:**
1. `tests/features/test_patch.py` uses OLD `apply()` API returning `bool` — must update to `tuple[bool, str]`
2. `InsertAfterTool` is added to `basic_tools.py` but NOT registered anywhere — dead code

---

## Correct Evaluation Model (Universal)

**Three independent signals:**
1. `execution_result`: `"passed" | "failed" | "env_error" | "not_verified"` — did the written code run?
2. `made_changes`: bool — did the agent actually write/modify anything?
3. `judge_score`: float 0.0-1.0 — LLM judge semantic quality evaluation

**`success` decision:**
- `success = made_changes AND execution_result NOT IN ("failed",)`
- `env_error` does NOT fail the agent — environment issues are not the agent's fault
- `not_verified` is acceptable — judge compensates
- Judge ALWAYS runs (deferred to end of suite), regardless of execution_result

**`success_mode` in config (optional):**
- `combined` (default): success = made_changes AND execution_result != "failed"
- `strict`: success = execution_result == "passed"
- `judge_only`: success = judge_score >= 0.7

---

## Phase 1: Fix Broken Tests + Register InsertAfterTool

### 1.1 Fix `tests/features/test_patch.py`

File: `tests/features/test_patch.py`

The file currently does:
```python
success = applier.apply(worktree_path=str(temp_repo_with_file), patch_text=patch_content)
assert success is True
```

But `PatchApplier.apply()` now returns `tuple[bool, str]`. Update ALL test calls:
```python
success, err = applier.apply(worktree_path=str(temp_repo_with_file), patch_text=patch_content)
assert success is True
assert err == ""
```

For the failure test:
```python
success, err = applier.apply(str(temp_repo_with_file), "not a patch")
assert success is False
assert len(err) > 0  # should have error detail
```

### 1.2 Register InsertAfterTool in benchmark orchestrator

File: `src/orchestrator/benchmark.py`

In the imports at the top, add:
```python
from src.features.tool_registry.basic_tools import (
    FileReadTool,
    FileWriteTool,
    GlobTool,
    PatchApplierTool,
    ReadAllTool,
    InsertAfterTool,   # ADD THIS
)
```

In `_get_tools_for_config()`, add to `tool_map`:
```python
"insert_after": InsertAfterTool(worktree_path),
```

File: `configs/benchmark_configs.yaml`

Add `"insert_after"` to ALL 20 config `tools:` lists. It should appear alongside `"write"` and `"patch"`. Example:
```yaml
tools: ["repo_map", "simple_rag", "read", "write", "patch", "insert_after", "shell"]
```

**Important:** `insert_after` is a write tool (not retrieval). Add it to every config's tools list.

---

## Phase 2: Universal ExecutionValidator (replaces `_validate_run`)

### 2.1 New file: `src/features/execution_validator.py`

Create this file with the `ExecutionValidator` class:

```python
"""
Universal execution validator for benchmark runs.

Does NOT assume the task involves tests. Can validate any coding task.
Returns one of: "passed" | "failed" | "env_error" | "not_verified"

Priority:
1. validation_cmd (if specified in BenchmarkMeta) — most specific
2. test_cmd + test files changed + baseline comparison — for test-writing tasks
3. python -m py_compile on changed .py files — syntax check fallback
4. not_verified — judge decides
"""
import logging
import os
import re
import subprocess
from dataclasses import dataclass

_log = logging.getLogger(__name__)

# Exit codes / stderr patterns that indicate environment failure (not agent failure)
_ENV_ERROR_PATTERNS = [
    r"ModuleNotFoundError",
    r"No module named",
    r"command not found",
    r"No such file or directory",
    r"Connection refused",
    r"ECONNREFUSED",
    r"address already in use",
    r"Permission denied",
    r"Cannot connect",
    r"uvicorn",  # server start issues
]

_ENV_ERROR_EXIT_CODES = {126, 127}


@dataclass
class ExecutionResult:
    outcome: str  # "passed" | "failed" | "env_error" | "not_verified"
    tests_passed: int = 0
    tests_failed: int = 0
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    method_used: str = ""  # "validation_cmd" | "test_cmd" | "syntax_check" | "none"


class ExecutionValidator:
    """
    Universal execution validator. Works regardless of task type or whether
    the target project has tests.
    """

    def __init__(self, worktree_path: str, run_dir: str | None = None):
        self.worktree_path = worktree_path
        self.run_dir = run_dir

    def validate(
        self,
        validation_cmd: str | None,
        test_cmd: str | None,
        baseline_pass_count: int | None,
        eval_env: dict | None = None,
    ) -> ExecutionResult:
        """
        Run validation. Returns ExecutionResult.
        """
        # Check if agent made any changes at all
        changed_files = self._get_changed_files()
        if not changed_files:
            return ExecutionResult(outcome="not_verified", method_used="none")

        # Priority 1: explicit validation_cmd
        if validation_cmd:
            return self._run_cmd(validation_cmd, method="validation_cmd", eval_env=eval_env)

        # Priority 2: test_cmd with baseline comparison
        if test_cmd:
            test_files = [f for f in changed_files if self._is_test_file(f)]
            if test_files or baseline_pass_count is not None:
                return self._run_test_cmd(test_cmd, baseline_pass_count, eval_env=eval_env)

        # Priority 3: syntax check on changed Python files
        py_files = [f for f in changed_files if f.endswith(".py")]
        if py_files:
            return self._syntax_check(py_files)

        return ExecutionResult(outcome="not_verified", method_used="none")

    def _get_changed_files(self) -> list[str]:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.worktree_path, capture_output=True, text=True, timeout=10
        )
        files = []
        for line in result.stdout.splitlines():
            if len(line) < 3:
                continue
            fname = line[3:].strip()
            if " -> " in fname:
                fname = fname.split(" -> ", 1)[1]
            files.append(fname)
        return files

    def _is_test_file(self, path: str) -> bool:
        base = os.path.basename(path)
        return (
            path.startswith("tests/") or
            base.startswith("test_") or
            base.endswith("_test.py")
        )

    def _is_env_error(self, stdout: str, stderr: str, exit_code: int) -> bool:
        if exit_code in _ENV_ERROR_EXIT_CODES:
            return True
        combined = stdout + stderr
        return any(re.search(p, combined) for p in _ENV_ERROR_PATTERNS)

    def _parse_pytest_counts(self, output: str) -> tuple[int, int]:
        passed = failed = 0
        for m in re.finditer(r'(\d+) passed|(\d+) failed|(\d+) error', output, re.IGNORECASE):
            if m.group(1):
                passed = int(m.group(1))
            elif m.group(2):
                failed += int(m.group(2))
            elif m.group(3):
                failed += int(m.group(3))
        return passed, failed

    def _run_cmd(self, cmd: str, method: str, eval_env: dict | None) -> ExecutionResult:
        import shlex
        env = eval_env or {k: v for k, v in os.environ.items() if k != 'UV_PROJECT_ENVIRONMENT'}
        env['UV_PROJECT_ENVIRONMENT'] = os.path.join(self.worktree_path, '.eval_venv')
        try:
            proc = subprocess.run(
                shlex.split(cmd),
                cwd=self.worktree_path,
                capture_output=True, text=True,
                timeout=300, env=env
            )
        except subprocess.TimeoutExpired:
            return ExecutionResult(outcome="env_error", method_used=method, stderr="Timeout")
        except Exception as e:
            return ExecutionResult(outcome="env_error", method_used=method, stderr=str(e))

        combined = proc.stdout + proc.stderr
        passed, failed_count = self._parse_pytest_counts(combined)

        if proc.returncode == 0:
            outcome = "passed"
        elif self._is_env_error(proc.stdout, proc.stderr, proc.returncode):
            outcome = "env_error"
        else:
            outcome = "failed"

        return ExecutionResult(
            outcome=outcome,
            tests_passed=passed,
            tests_failed=failed_count,
            stdout=proc.stdout[-3000:],
            stderr=proc.stderr[-1000:],
            exit_code=proc.returncode,
            method_used=method,
        )

    def _run_test_cmd(self, test_cmd: str, baseline_pass_count: int | None, eval_env: dict | None) -> ExecutionResult:
        result = self._run_cmd(test_cmd, method="test_cmd", eval_env=eval_env)
        if result.outcome == "passed" and baseline_pass_count is not None:
            if result.tests_passed < baseline_pass_count:
                _log.warning(
                    "Regression: baseline %d tests, now %d. Agent may have destroyed tests.",
                    baseline_pass_count, result.tests_passed
                )
                result.outcome = "failed"
                result.stderr += f"\nREGRESSION: {baseline_pass_count} tests baseline, {result.tests_passed} now"
        return result

    def _syntax_check(self, py_files: list[str]) -> ExecutionResult:
        errors = []
        for rel_path in py_files:
            full_path = os.path.join(self.worktree_path, rel_path)
            if not os.path.isfile(full_path):
                continue
            proc = subprocess.run(
                ["python", "-m", "py_compile", full_path],
                capture_output=True, text=True, timeout=10
            )
            if proc.returncode != 0:
                errors.append(f"{rel_path}: {proc.stderr.strip()}")
        if errors:
            return ExecutionResult(
                outcome="failed",
                stderr="\n".join(errors),
                method_used="syntax_check",
            )
        return ExecutionResult(outcome="not_verified", method_used="syntax_check")
```

### 2.2 Capture baseline before suite

File: `src/orchestrator/benchmark.py`

Add `_capture_baseline()` method:

```python
def _capture_baseline(self) -> int | None:
    """
    Run test_cmd on the target repo ONCE before the suite to establish baseline pass count.
    Returns pass count or None if test_cmd not available or fails to run.
    """
    if not self.test_cmd:
        return None
    import shlex, re
    env = {k: v for k, v in os.environ.items()}
    try:
        proc = subprocess.run(
            shlex.split(self.test_cmd),
            cwd=self.repo_path,
            capture_output=True, text=True,
            timeout=300, env=env
        )
        combined = proc.stdout + proc.stderr
        m = re.search(r'(\d+) passed', combined)
        if m:
            count = int(m.group(1))
            self.logger.info("Baseline: %d tests passing in target repo.", count)
            return count
    except Exception as e:
        self.logger.warning("Could not capture baseline: %s", e)
    return None
```

Call `self._baseline_pass_count = self._capture_baseline()` at the start of `run_suite()` before the config loop.

### 2.3 Integrate ExecutionValidator into AgnoRunner

File: `src/features/agent_integration/agno_runner.py`

Replace `_validate_run()` method entirely. The new method should use `ExecutionValidator`:

```python
def _validate_run(
    self,
    worktree_path: str,
    test_cmd: str,
    validation_cmd: str | None = None,
    baseline_pass_count: int | None = None,
) -> tuple[str, int, int]:
    """
    Returns (outcome, tests_passed, patch_lines).
    outcome: "passed" | "failed" | "env_error" | "not_verified"
    """
    from src.features.execution_validator import ExecutionValidator
    
    # Get patch lines first
    patch_lines = 0
    try:
        diff = subprocess.run(
            ["git", "diff", "HEAD"], cwd=worktree_path, capture_output=True, text=True
        )
        patch_lines = len([l for l in diff.stdout.splitlines() if l.startswith(('+', '-'))])
        if self.run_dir and os.path.isdir(self.run_dir):
            with open(os.path.join(self.run_dir, "final.patch"), "w", encoding="utf-8") as f:
                f.write(diff.stdout)
    except Exception:
        pass
    
    eval_env = {k: v for k, v in os.environ.items() if k != 'UV_PROJECT_ENVIRONMENT'}
    eval_env['UV_PROJECT_ENVIRONMENT'] = os.path.join(worktree_path, '.eval_venv')
    
    validator = ExecutionValidator(worktree_path, run_dir=self.run_dir)
    result = validator.validate(
        validation_cmd=validation_cmd,
        test_cmd=test_cmd,
        baseline_pass_count=baseline_pass_count,
        eval_env=eval_env,
    )
    
    # Save execution result to run_dir
    if self.run_dir and os.path.isdir(self.run_dir):
        import json
        exec_path = os.path.join(self.run_dir, "execution_result.json")
        with open(exec_path, "w", encoding="utf-8") as f:
            json.dump({
                "outcome": result.outcome,
                "tests_passed": result.tests_passed,
                "tests_failed": result.tests_failed,
                "exit_code": result.exit_code,
                "method_used": result.method_used,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }, f, indent=2)
    
    if result.outcome in ("passed", "not_verified", "env_error"):
        _log.info("Validation outcome: %s (method: %s)", result.outcome, result.method_used)
    else:
        _log.warning("Validation outcome: %s (method: %s)\n%s",
                     result.outcome, result.method_used, result.stderr[-500:])
    
    return result.outcome, result.tests_passed, patch_lines
```

The callers in `run()` and `_run_with_mcp()` that currently use:
```python
success, tests_passed, patch_lines = self._validate_run(worktree_path, test_cmd)
```

Must be updated to:
```python
exec_outcome, tests_passed, patch_lines = self._validate_run(
    worktree_path, test_cmd,
    validation_cmd=getattr(self, 'validation_cmd', None),
    baseline_pass_count=getattr(self, 'baseline_pass_count', None),
)
success = (exec_outcome != "failed") and bool(patch_lines > 0)
```

Also add `validation_cmd: str | None = None` and `baseline_pass_count: int | None = None` to `AgnoRunner.__init__()`.

### 2.4 Update models.py for new fields

File: `src/core/models.py`

Update `BenchmarkMeta`:
```python
class BenchmarkMeta(BaseModel):
    repo: str
    task: str
    test_cmd: str = "pytest"
    timeout_sec: int = 600
    validation_cmd: str | None = None        # ADD: explicit validation command
    success_mode: str = "combined"           # ADD: "combined" | "strict" | "judge_only"
    max_cost_usd_suite: float = 5.0          # ADD: max cost for full suite run
    max_cost_usd_config: float = 0.15        # ADD: max cost per single config
    max_tokens_per_config: int = 500_000     # ADD: max tokens per config
```

Update `RunMetrics`:
```python
class RunMetrics(BaseModel):
    success: bool
    eval_score: float
    input_tokens: int
    output_tokens: int
    tool_tokens: int
    duration_sec: float
    model_calls: int
    tool_calls: int
    model_name: str = "gemini-2.5-flash"
    tests_passed: int = 0
    files_read: int = 0
    files_changed: int = 0
    patch_lines: int = 0
    errors: int = 0
    # NEW fields:
    execution_result: str = "not_verified"   # "passed"|"failed"|"env_error"|"not_verified"
    made_changes: bool = False               # did agent make any file changes
    cost_exceeded: bool = False              # exceeded per-config cost limit
    token_exceeded: bool = False             # exceeded per-config token limit
    write_tool_failures: int = 0            # consecutive write tool failures
    content_destruction_warning: bool = False  # file shrunk >50%
    # Judge fields (unchanged):
    task_solved_score: float = 0.0
    tool_correctness_score: float = 0.0
    judge_reasoning_task: str = ""
    judge_reasoning_tools: str = ""
    judge_model: str = ""
```

---

## Phase 3: Shell Tool in All Configs + Agent Instructions

### 3.1 Update benchmark_configs.yaml

File: `configs/benchmark_configs.yaml`

Add to the `benchmark:` section:
```yaml
benchmark:
  repo: "C:\\Users\\User\\a_projects\\process_metrics_platform_v2"
  test_cmd: "uv run --extra dev pytest tests/unit/ -x -q"
  timeout_sec: 1200
  max_cost_usd_suite: 5.00
  max_cost_usd_config: 0.15
  max_tokens_per_config: 500000
  task: >
    ...
```

For ALL 20 configs, add `"shell"` and `"insert_after"` to the tools list. Examples:
```yaml
- id: "01_cursor_like"
  tools: ["repo_map", "simple_rag", "read", "write", "patch", "insert_after", "shell"]

- id: "02_claude_code_like"
  tools: ["glob", "rg", "read", "write", "patch", "insert_after", "shell"]
```

Every single config must have both `"insert_after"` and `"shell"` in its tools list.

### 3.2 Update ShellTool description

File: `src/features/tool_registry/shell_tool.py`

Update the description in `__init__`:
```python
super().__init__(
    "shell",
    "Runs shell/bash commands in the repository directory. "
    "IMPORTANT: Use this to verify your code after writing it. "
    "Example: shell(command='python -m py_compile src/myfile.py') to check syntax. "
    "Or: shell(command='uv run pytest tests/unit/test_foo.py -x -q') if tests exist. "
    "Always run a verification command before declaring TASK_COMPLETE."
)
```

### 3.3 Update agent instructions

File: `src/features/agent_integration/agno_runner.py`

Replace the `instructions` list in BOTH `Agent(...)` instantiations (in `run()` and `_run_with_mcp()`):

```python
instructions=[
    f"You are a coding agent working in the repository at: {worktree_path}",
    "Complete the task using ONLY the tools provided.",
    "Always use RELATIVE file paths (relative to the repository root) when calling file tools. Never use absolute paths.",
    "WRITING TOOLS: Use 'patch' to apply targeted diffs, 'insert_after' to add code after an anchor line without overwriting, or 'write' to write a complete file. Prefer 'insert_after' when adding new functions/classes to an existing file to avoid destroying existing content.",
    "MANDATORY VERIFICATION: After writing code, ALWAYS use 'shell' to verify it works before TASK_COMPLETE. Run syntax check or tests. Fix any errors you find.",
    "TASK_COMPLETE: Output exactly 'TASK_COMPLETE' only after: (1) you have written code with write/patch/insert_after, AND (2) you have verified the code runs with shell.",
    "If a tool returns an error, try a different approach. Do not repeat the exact same failing call.",
    "If patch fails, fall back to insert_after (for additions) or write (for complete rewrites).",
],
```

### 3.4 Update prompt_builder.py

File: `src/features/prompt_builder.py`

Update the exclusion set — `shell` and `insert_after` are infrastructure tools, not retrieval strategies:
```python
_ALWAYS_EXCLUDED = {"test", "patch", "write", "insert_after", "shell"}

def build_tool_restriction_prefix(config: AgentConfig) -> str:
    retrieval_tools = sorted(set(config.tools) - _ALWAYS_EXCLUDED)
    write_tools = [t for t in config.tools if t in ("write", "patch", "insert_after")]
    ...
```

---

## Phase 4: Stale Worktree Cleanup

File: `src/features/isolation.py`

Add `cleanup_stale()` method to `GitIsolationProvider`:

```python
def cleanup_stale(self) -> list[str]:
    """
    Prune stale worktree git entries and remove orphaned directories.
    Returns list of cleaned-up paths.
    """
    cleaned = []
    
    # Step 1: git worktree prune
    try:
        subprocess.run(
            [self.git_cmd, "worktree", "prune"],
            cwd=self.repo_path, capture_output=True, timeout=30
        )
    except Exception as e:
        logging.getLogger(__name__).warning("git worktree prune failed: %s", e)
    
    # Step 2: remove orphaned directories in worktree_base
    if not os.path.isdir(self.worktree_base):
        return cleaned
    
    active_paths = set(self.active_worktrees.values())
    for entry in os.listdir(self.worktree_base):
        full_path = os.path.join(self.worktree_base, entry)
        if not os.path.isdir(full_path):
            continue
        if full_path not in active_paths:
            try:
                # Try git remove first
                subprocess.run(
                    [self.git_cmd, "worktree", "remove", "--force", full_path],
                    cwd=self.repo_path, capture_output=True, timeout=30
                )
            except Exception:
                pass
            if os.path.exists(full_path):
                shutil.rmtree(full_path, ignore_errors=True)
            cleaned.append(full_path)
            logging.getLogger(__name__).info("Cleaned stale worktree: %s", full_path)
    
    return cleaned
```

File: `src/orchestrator/benchmark.py`

In `run_suite()`, after `self._run_preflight()` and before the config loop, add:
```python
stale = self.isolation.cleanup_stale()
if stale:
    self.logger.info("Cleaned up %d stale worktrees: %s", len(stale), stale)
```

Do the same in `run_failed_configs()`.

---

## Phase 5: Cost Guard

### 5.1 New file: `src/features/cost_guard.py`

```python
"""
CostGuard: tracks cumulative cost and token usage during a benchmark suite run.
Enforces per-config and per-suite budget limits defined in BenchmarkMeta.
"""
import logging

_log = logging.getLogger(__name__)


class BudgetExceededError(RuntimeError):
    """Raised when the suite-level cost budget is exhausted."""


class CostGuard:
    def __init__(self, max_suite_usd: float = 5.0, max_config_usd: float = 0.15,
                 max_tokens_per_config: int = 500_000):
        self.max_suite_usd = max_suite_usd
        self.max_config_usd = max_config_usd
        self.max_tokens_per_config = max_tokens_per_config
        self.suite_spent_usd: float = 0.0
        self.suite_total_tokens: int = 0
        self.config_costs: dict[str, float] = {}

    def check_suite_budget(self, next_config_id: str) -> None:
        """
        Call BEFORE starting each config run.
        Raises BudgetExceededError if suite budget is exhausted.
        """
        if self.suite_spent_usd >= self.max_suite_usd:
            raise BudgetExceededError(
                f"Suite budget exhausted: ${self.suite_spent_usd:.4f} >= "
                f"${self.max_suite_usd:.2f}. Skipping {next_config_id} and all remaining configs."
            )

    def record(self, config_id: str, cost_usd: float, total_tokens: int) -> dict[str, bool]:
        """
        Call AFTER each config run completes.
        Returns dict of budget flags: {"cost_exceeded": bool, "token_exceeded": bool}
        """
        self.config_costs[config_id] = cost_usd
        self.suite_spent_usd += cost_usd
        self.suite_total_tokens += total_tokens
        
        cost_exceeded = cost_usd > self.max_config_usd
        token_exceeded = total_tokens > self.max_tokens_per_config
        
        if cost_exceeded:
            _log.warning(
                "Config %s exceeded per-config cost limit: $%.4f > $%.4f",
                config_id, cost_usd, self.max_config_usd
            )
        if token_exceeded:
            _log.warning(
                "Config %s exceeded per-config token limit: %d > %d",
                config_id, total_tokens, self.max_tokens_per_config
            )
        _log.info(
            "Suite spent so far: $%.4f / $%.2f (configs: %d)",
            self.suite_spent_usd, self.max_suite_usd, len(self.config_costs)
        )
        return {"cost_exceeded": cost_exceeded, "token_exceeded": token_exceeded}

    @property
    def suite_summary(self) -> dict:
        return {
            "total_cost_usd": self.suite_spent_usd,
            "total_tokens": self.suite_total_tokens,
            "config_costs": self.config_costs,
            "budget_limit_usd": self.max_suite_usd,
        }
```

### 5.2 Integrate CostGuard in orchestrator

File: `src/orchestrator/benchmark.py`

In `__init__()`, accept cost params:
```python
def __init__(
    self,
    repo_path: str,
    configs_path: str,
    results_dir: str,
    worktree_base: str = "worktrees",
    dry_run: bool = False,
    timeout_sec: int = 600,
    max_cost_usd_suite: float = 5.0,
    max_cost_usd_config: float = 0.15,
    max_tokens_per_config: int = 500_000,
    **_kwargs,
):
    ...
    self.max_cost_usd_suite = max_cost_usd_suite
    self.max_cost_usd_config = max_cost_usd_config
    self.max_tokens_per_config = max_tokens_per_config
```

In `run_suite()`:
```python
from src.features.cost_guard import CostGuard, BudgetExceededError

cost_guard = CostGuard(
    max_suite_usd=self.max_cost_usd_suite,
    max_config_usd=self.max_cost_usd_config,
    max_tokens_per_config=self.max_tokens_per_config,
)

# Inside the config loop, BEFORE starting the config:
try:
    cost_guard.check_suite_budget(config.id)
except BudgetExceededError as e:
    self.logger.error("STOPPING SUITE: %s", e)
    break

# AFTER config run completes (after run_metrics is available):
budget_flags = cost_guard.record(
    config.id,
    run_metrics.cost_usd,
    run_metrics.total_tokens,
)
# Update run_metrics with budget flags:
run_metrics = run_metrics.model_copy(update={
    "cost_exceeded": budget_flags["cost_exceeded"],
    "token_exceeded": budget_flags["token_exceeded"],
})
```

At end of suite, log summary:
```python
self.logger.info("Cost summary: %s", cost_guard.suite_summary)
```

File: `main.py`

Pass cost params from meta to orchestrator:
```python
orchestrator = BenchmarkOrchestrator(
    repo_path=repo,
    configs_path=args.configs,
    results_dir=args.results,
    test_cmd=test_cmd,
    worktree_base=args.worktree_base,
    dry_run=args.dry_run,
    timeout_sec=timeout_sec,
    max_cost_usd_suite=meta.max_cost_usd_suite if meta else 5.0,
    max_cost_usd_config=meta.max_cost_usd_config if meta else 0.15,
    max_tokens_per_config=meta.max_tokens_per_config if meta else 500_000,
)
```

---

## Phase 6: Run Event Logging

File: `src/features/agent_integration/agno_runner.py`

Add `_save_run_artifacts()` method, called after agent run and after `_validate_run`:

```python
def _save_run_artifacts(
    self,
    response: "RunOutput",
    execution_outcome: str,
    patch_lines: int,
    worktree_path: str,
) -> None:
    """Save detailed run artifacts to run_dir for eval."""
    if not self.run_dir or not os.path.isdir(self.run_dir):
        return

    # 1. tool_calls.jsonl
    try:
        tool_calls_path = os.path.join(self.run_dir, "tool_calls.jsonl")
        with open(tool_calls_path, "w", encoding="utf-8") as f:
            for step, tool_exec in enumerate(response.tools or [], start=1):
                name = tool_exec.tool_name or "unknown"
                is_error = bool(tool_exec.tool_call_error)
                res_str = str(getattr(tool_exec, "result", "") or "")
                if res_str.startswith("Error:"):
                    is_error = True
                # Summarize args to avoid huge files
                args_raw = getattr(tool_exec, "tool_call_args", {}) or {}
                args_preview = {k: str(v)[:100] for k, v in (args_raw.items() if isinstance(args_raw, dict) else {})}
                record = {
                    "step": step,
                    "tool": name,
                    "args_preview": args_preview,
                    "result_len": len(res_str),
                    "is_error": is_error,
                }
                f.write(json.dumps(record) + "\n")
    except Exception as e:
        _log.warning("Failed to save tool_calls.jsonl: %s", e)

    # 2. file_changes.json — from git diff --stat
    try:
        diff_stat = subprocess.run(
            ["git", "diff", "HEAD", "--numstat"],
            cwd=worktree_path, capture_output=True, text=True, timeout=10
        )
        files_info = []
        content_destruction_warning = False
        for line in diff_stat.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                insertions = int(parts[0]) if parts[0].isdigit() else 0
                deletions = int(parts[1]) if parts[1].isdigit() else 0
                path = parts[2]
                # Check for content destruction: get original line count
                orig_result = subprocess.run(
                    ["git", "show", f"HEAD:{path}"],
                    cwd=worktree_path, capture_output=True, text=True, timeout=10
                )
                orig_lines = len(orig_result.stdout.splitlines()) if orig_result.returncode == 0 else 0
                new_lines = orig_lines + insertions - deletions
                if orig_lines > 10 and new_lines < orig_lines * 0.5:
                    content_destruction_warning = True
                files_info.append({
                    "path": path,
                    "insertions": insertions,
                    "deletions": deletions,
                    "prev_lines": orig_lines,
                    "new_lines": max(0, new_lines),
                })
        changes_path = os.path.join(self.run_dir, "file_changes.json")
        with open(changes_path, "w", encoding="utf-8") as f:
            json.dump({
                "files": files_info,
                "total_insertions": sum(fi["insertions"] for fi in files_info),
                "total_deletions": sum(fi["deletions"] for fi in files_info),
                "content_destruction_warning": content_destruction_warning,
            }, f, indent=2)
    except Exception as e:
        _log.warning("Failed to save file_changes.json: %s", e)
```

Call `self._save_run_artifacts(response, exec_outcome, patch_lines, worktree_path)` after `_validate_run()` in both `run()` and `_run_with_mcp()`.

Also update RunMetrics with `content_destruction_warning` from `file_changes.json` if needed.

---

## Phase 7: Deferred LLM Judge

File: `src/orchestrator/benchmark.py`

### 7.1 Add PendingJudge dataclass

At the top of `benchmark.py`:
```python
from dataclasses import dataclass
from typing import Any

@dataclass
class PendingJudge:
    run_id: str
    config_id: str
    full_task: str
    log_path: str
    patch_path: str
    config_tools: list[str]
    run_metrics: Any  # RunMetrics
```

### 7.2 Remove inline judge from config loops

In BOTH `run_suite()` and `run_failed_configs()`, remove the entire LLM Judge Evaluation block (the try block that creates `LLMJudge()` and calls `judge.evaluate()`).

Instead, after getting `run_metrics`, append to a pending list:
```python
judge_queue.append(PendingJudge(
    run_id=run_id,
    config_id=config.id,
    full_task=full_task,
    log_path=log_path,
    patch_path=os.path.join(run_dir, "final.patch"),
    config_tools=config.tools,
    run_metrics=run_metrics,
))
```

Initialize `judge_queue: list[PendingJudge] = []` before the config loop.

### 7.3 Add batch judge after loop

After the config loop ends (before `self.logger.info("Benchmark suite completed.")`):

```python
self.logger.info("Running deferred LLM judge for %d configs...", len(judge_queue))
judge = LLMJudge()
for pending in judge_queue:
    try:
        messages_data = []
        if os.path.exists(pending.log_path):
            with open(pending.log_path, encoding="utf-8") as f:
                messages_data = json.load(f)
        patch_content = None
        if os.path.exists(pending.patch_path):
            with open(pending.patch_path, encoding="utf-8") as f:
                patch_content = f.read()
        
        report = judge.evaluate(
            task_description=pending.full_task,
            agent_messages=messages_data,
            patch=patch_content,
            config_tools=pending.config_tools,
            tests_passed=pending.run_metrics.tests_passed,
            tests_total=pending.run_metrics.tests_passed + pending.run_metrics.errors,
            success=pending.run_metrics.success,
        )
        updated_metrics = pending.run_metrics.model_copy(update={
            "task_solved_score": report.task_solved_score,
            "tool_correctness_score": report.tool_correctness_score,
            "judge_reasoning_task": report.task_solved_reasoning,
            "judge_reasoning_tools": report.tool_correctness_reasoning,
            "judge_model": report.judge_model,
        })
        # Re-save updated result
        updated_result = EvalResult(
            run_id=pending.run_id,
            config_id=pending.config_id,
            metrics=updated_metrics,
            success=updated_metrics.success,
            error=None,
            patch=None,
        )
        self.aggregator.save_run(updated_result)
        self.logger.info("Judge complete for %s: task=%.2f, tools=%.2f",
                         pending.config_id, report.task_solved_score, report.tool_correctness_score)
    except Exception as e:
        self.logger.warning("Judge failed for %s: %s", pending.config_id, e)
```

Apply the same pattern to `run_failed_configs()`.

---

## Phase 8: Per-Tool Validator Structure

### 8.1 Create base validator ABC

File: `src/features/tool_registry/base.py` (NEW FILE)

```python
"""
Base abstractions for tool validators.
"""
from __future__ import annotations
import logging
import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar


@dataclass
class ValidationResult:
    passed: bool
    detail: str = ""
    warning: bool = False  # passed but with a concern


class BaseToolValidator(ABC):
    """
    Universal connector for each benchmark tool.
    Provides: installation check, smoke test, Agno registration check,
    configuration, and expensive preparation (RAG ingestion, etc.).
    """
    tool_name: ClassVar[str]
    cli_binary: ClassVar[str | None] = None

    # Platform-specific install commands: {"linux": "apt-get install -y rg", "mac": "brew install rg", ...}
    # Platforms: "linux", "mac", "wsl", "windows"
    platform_install_cmds: ClassVar[dict[str, str]] = {}

    def check_installed(self) -> ValidationResult:
        """Check if the tool binary/package is available."""
        if self.cli_binary is None:
            return ValidationResult(passed=True, detail="pure Python, no CLI needed")
        found = __import__("shutil").which(self.cli_binary) is not None
        return ValidationResult(
            passed=found,
            detail=f"'{self.cli_binary}' found in PATH" if found else f"'{self.cli_binary}' not found in PATH",
        )

    @abstractmethod
    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        """Run a minimal functionality test. tmp_dir is a temp directory with a sample Python file."""
        ...

    def validate_agno_registration(self, tmp_dir: str) -> ValidationResult:
        """
        Start a mini Agno agent with this tool and verify the tool appears in agent.tools.
        Default implementation for non-MCP tools.
        """
        try:
            from agno.agent import Agent
            from agno.models.openai import OpenAIChat
            from agno.tools import tool as agno_tool
            from src.core.tools import Tool
            
            # Get a real tool instance
            tool_instance = self._get_tool_instance(tmp_dir)
            if tool_instance is None:
                return ValidationResult(passed=False, detail="Could not instantiate tool")
            
            # Build agno wrapper
            import inspect
            sig = inspect.signature(tool_instance.execute)
            globs = {"_tool": tool_instance}
            parts, args = [], []
            for name, param in sig.parameters.items():
                ann = param.annotation if param.annotation is not inspect.Parameter.empty else str
                globs[f"_t_{name}"] = ann
                args.append(f"{name}={name}")
                if param.default is inspect.Parameter.empty:
                    parts.append(f"{name}: _t_{name}")
                else:
                    globs[f"_d_{name}"] = param.default
                    parts.append(f"{name}: _t_{name} = _d_{name}")
            src = (
                f"def {tool_instance.name}({', '.join(parts)}) -> str:\n"
                f"    return _tool.execute({', '.join(args)}).output\n"
            )
            exec(src, globs)
            fn = globs[tool_instance.name]
            fn.__doc__ = tool_instance.description
            wrapped = agno_tool(fn)
            
            # Create agent and check tool appears
            # Use a dummy model that doesn't need an API key for tool listing
            agent = Agent(tools=[wrapped], markdown=False)
            tool_names = [t.name if hasattr(t, 'name') else str(t) for t in (agent.tools or [])]
            
            if tool_instance.name in str(tool_names):
                return ValidationResult(passed=True, detail=f"Tool '{tool_instance.name}' registered in Agno agent")
            return ValidationResult(passed=False, detail=f"Tool '{tool_instance.name}' NOT found in agent.tools: {tool_names}")
        except Exception as e:
            return ValidationResult(passed=False, detail=f"Agno registration check failed: {e}")

    def _get_tool_instance(self, tmp_dir: str):
        """Override in subclass to return the actual tool instance for this validator."""
        return None

    def configure(self, repo_path: str) -> ValidationResult:
        """One-time configuration (e.g., create .serena/project.yml)."""
        return ValidationResult(passed=True, detail="no configuration needed")

    def prepare(self, repo_path: str) -> ValidationResult:
        """Expensive one-time preparation (e.g., RAG ingestion, repo map build)."""
        return ValidationResult(passed=True, detail="no preparation needed")

    def install(self, platform: str) -> ValidationResult:
        """Attempt to install the tool on the given platform."""
        cmd = self.platform_install_cmds.get(platform)
        if not cmd:
            return ValidationResult(
                passed=False,
                detail=f"No install command defined for platform '{platform}'. Install '{self.cli_binary}' manually."
            )
        try:
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
            if proc.returncode == 0:
                return ValidationResult(passed=True, detail=f"Installed via: {cmd}")
            return ValidationResult(passed=False, detail=f"Install failed (exit {proc.returncode}): {proc.stderr.strip()[:200]}")
        except Exception as e:
            return ValidationResult(passed=False, detail=f"Install error: {e}")
```

### 8.2 Create per-tool validator files

Create the following directory structure. Each file is a minimal `validator.py`:

**`src/features/tool_registry/tools/__init__.py`** — empty

**`src/features/tool_registry/tools/grep/__init__.py`** — empty

**`src/features/tool_registry/tools/grep/validator.py`**:
```python
from src.features.tool_registry.base import BaseToolValidator, ValidationResult
from src.features.tool_registry.grep_tools import GrepTool


class GrepValidator(BaseToolValidator):
    tool_name = "grep"
    cli_binary = "grep"
    platform_install_cmds = {
        "linux": "sudo apt-get install -y grep",
        "wsl": "sudo apt-get install -y grep",
    }

    def _get_tool_instance(self, tmp_dir): return GrepTool(tmp_dir)

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        tool = GrepTool(tmp_dir)
        result = tool.execute(pattern="hello_world")
        passed = "Error:" not in str(result.output)
        return ValidationResult(passed=passed, detail=str(result.output)[:100])
```

**`src/features/tool_registry/tools/rg/validator.py`**:
```python
from src.features.tool_registry.base import BaseToolValidator, ValidationResult
from src.features.tool_registry.grep_tools import RgTool


class RgValidator(BaseToolValidator):
    tool_name = "rg"
    cli_binary = "rg"
    platform_install_cmds = {
        "linux": "sudo apt-get install -y ripgrep",
        "wsl": "sudo apt-get install -y ripgrep",
        "mac": "brew install ripgrep",
        "windows": "winget install BurntSushi.ripgrep.MSVC",
    }

    def _get_tool_instance(self, tmp_dir): return RgTool(tmp_dir)

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        tool = RgTool(tmp_dir)
        result = tool.execute(pattern="hello_world")
        passed = "Error:" not in str(result.output)
        return ValidationResult(passed=passed, detail=str(result.output)[:100])
```

Create similar `validator.py` files for ALL remaining tools:
- `tools/git_grep/validator.py` — uses `GitGrepTool`, cli_binary="git"
- `tools/ugrep/validator.py` — uses `UgrepTool`, cli_binary="ugrep", install: apt/brew
- `tools/ast_grep/validator.py` — uses `AstGrepTool`, cli_binary="ast-grep", install: cargo/brew
- `tools/semgrep/validator.py` — uses `SemgrepTool`, cli_binary="semgrep", install: pip
- `tools/tree_sitter/validator.py` — uses `TreeSitterTool`, cli_binary=None, pure Python
- `tools/repo_map/validator.py` — uses `RepoMapTool`, cli_binary=None
- `tools/lsp_symbols/validator.py` — uses `LspSymbolsTool`, cli_binary=None
- `tools/read/validator.py` — uses `FileReadTool`, cli_binary=None
- `tools/write/validator.py` — uses `FileWriteTool`, cli_binary=None
- `tools/patch/validator.py` — uses `PatchApplierTool`, cli_binary=None (optionally "patch" for GNU)
- `tools/insert_after/validator.py` — uses `InsertAfterTool`, cli_binary=None
- `tools/shell/validator.py` — uses `ShellTool`, cli_binary=None
- `tools/glob/validator.py` — uses `GlobTool`, cli_binary=None

For `simple_rag`, override `prepare()`:
**`tools/simple_rag/validator.py`**:
```python
from src.features.tool_registry.base import BaseToolValidator, ValidationResult
from src.features.tool_registry.semantic_tools import SimpleRagTool


class SimpleRagValidator(BaseToolValidator):
    tool_name = "simple_rag"
    cli_binary = None

    def _get_tool_instance(self, tmp_dir): return SimpleRagTool(tmp_dir)

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        try:
            tool = SimpleRagTool(tmp_dir)
            # Just check it instantiates without error
            return ValidationResult(passed=True, detail="SimpleRagTool instantiated")
        except Exception as e:
            return ValidationResult(passed=False, detail=str(e))

    def prepare(self, repo_path: str) -> ValidationResult:
        """Expensive: ingest repository into RAG index."""
        try:
            tool = SimpleRagTool(repo_path)
            stats = tool.ingest()
            return ValidationResult(
                passed=stats.get("status") != "error",
                detail=f"RAG ingested: files={stats.get('files','?')}, chunks={stats.get('chunks','?')}"
            )
        except Exception as e:
            return ValidationResult(passed=False, detail=f"RAG ingestion failed: {e}")
```

For MCP tools (serena, semble), override `validate_agno_registration()`:
**`tools/serena/validator.py`**:
```python
import subprocess
from src.features.tool_registry.base import BaseToolValidator, ValidationResult


class SerenaValidator(BaseToolValidator):
    tool_name = "serena"
    cli_binary = "serena"
    platform_install_cmds = {
        "linux": "uv tool install serena",
        "wsl": "uv tool install serena",
        "windows": "uv tool install serena",
        "mac": "uv tool install serena",
    }

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        result = subprocess.run(
            ["serena", "--version"],
            capture_output=True, text=True, timeout=10
        )
        passed = result.returncode == 0
        return ValidationResult(passed=passed, detail=(result.stdout or result.stderr).strip()[:100])

    def configure(self, repo_path: str) -> ValidationResult:
        """Create minimal .serena/project.yml to avoid 4-min LSP startup."""
        import os, yaml
        serena_dir = os.path.join(repo_path, ".serena")
        config_path = os.path.join(serena_dir, "project.yml")
        if os.path.isfile(config_path):
            return ValidationResult(passed=True, detail="already configured")
        os.makedirs(serena_dir, exist_ok=True)
        project_cfg = {
            "project_name": os.path.basename(repo_path),
            "languages": ["python"],
            "encoding": "utf-8",
            "read_only": False,
            "excluded_tools": [],
            "included_optional_tools": [],
            "fixed_tools": [],
            "ignored_paths": [],
        }
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(project_cfg, f, default_flow_style=False)
        return ValidationResult(passed=True, detail=f"Created {config_path}")

    def validate_agno_registration(self, tmp_dir: str) -> ValidationResult:
        """For MCP tools, just verify the binary starts without error."""
        result = self.smoke_test(tmp_dir)
        if result.passed:
            return ValidationResult(passed=True, detail="Serena MCP binary available (full MCP session test requires target repo)")
        return result
```

**`tools/semble/validator.py`**: similar to serena but uses `uvx --from semble[mcp] semble --version`

### 8.3 Create ToolRegistry

File: `src/features/tool_registry/registry.py` (NEW FILE)

```python
"""
ToolRegistry: centralizes tool instantiation and validator lookup.
Replaces the inline tool_map in benchmark.py.
"""
from __future__ import annotations
import importlib
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.tools import Tool
    from src.features.tool_registry.base import BaseToolValidator

_log = logging.getLogger(__name__)

# Map tool_name -> (module, class) for validator discovery
_VALIDATOR_MAP: dict[str, tuple[str, str]] = {
    "grep":        ("src.features.tool_registry.tools.grep.validator",        "GrepValidator"),
    "rg":          ("src.features.tool_registry.tools.rg.validator",          "RgValidator"),
    "git_grep":    ("src.features.tool_registry.tools.git_grep.validator",     "GitGrepValidator"),
    "ugrep":       ("src.features.tool_registry.tools.ugrep.validator",        "UgrepValidator"),
    "ast_grep":    ("src.features.tool_registry.tools.ast_grep.validator",     "AstGrepValidator"),
    "semgrep":     ("src.features.tool_registry.tools.semgrep.validator",      "SemgrepValidator"),
    "tree_sitter": ("src.features.tool_registry.tools.tree_sitter.validator",  "TreeSitterValidator"),
    "repo_map":    ("src.features.tool_registry.tools.repo_map.validator",     "RepoMapValidator"),
    "simple_rag":  ("src.features.tool_registry.tools.simple_rag.validator",   "SimpleRagValidator"),
    "lsp_symbols": ("src.features.tool_registry.tools.lsp_symbols.validator",  "LspSymbolsValidator"),
    "serena":      ("src.features.tool_registry.tools.serena.validator",       "SerenaValidator"),
    "semble":      ("src.features.tool_registry.tools.semble.validator",       "SembleValidator"),
    "read":        ("src.features.tool_registry.tools.read.validator",         "ReadValidator"),
    "write":       ("src.features.tool_registry.tools.write.validator",        "WriteValidator"),
    "patch":       ("src.features.tool_registry.tools.patch.validator",        "PatchValidator"),
    "insert_after":("src.features.tool_registry.tools.insert_after.validator", "InsertAfterValidator"),
    "shell":       ("src.features.tool_registry.tools.shell.validator",        "ShellValidator"),
    "glob":        ("src.features.tool_registry.tools.glob.validator",         "GlobValidator"),
}


class ToolRegistry:
    @classmethod
    def build_tool_map(cls, worktree_path: str) -> dict[str, "Tool"]:
        """Build full tool_map from all registered tool classes."""
        from src.features.tool_registry.basic_tools import (
            FileReadTool, FileWriteTool, GlobTool, PatchApplierTool, ReadAllTool, InsertAfterTool
        )
        from src.features.tool_registry.grep_tools import (
            AstGrepTool, GitGrepTool, GrepTool, RgTool, SemgrepTool, UgrepTool
        )
        from src.features.tool_registry.lsp_tools import LspSymbolsTool
        from src.features.tool_registry.semantic_tools import SimpleRagTool
        from src.features.tool_registry.shell_tool import ShellTool
        from src.features.tool_registry.structural_tools import RepoMapTool, TreeSitterTool

        return {
            "read": FileReadTool(worktree_path),
            "read_all": ReadAllTool(worktree_path),
            "write": FileWriteTool(worktree_path),
            "patch": PatchApplierTool(worktree_path),
            "insert_after": InsertAfterTool(worktree_path),
            "glob": GlobTool(worktree_path),
            "rg": RgTool(worktree_path),
            "grep": GrepTool(worktree_path),
            "git_grep": GitGrepTool(worktree_path),
            "ugrep": UgrepTool(worktree_path),
            "ast_grep": AstGrepTool(worktree_path),
            "semgrep": SemgrepTool(worktree_path),
            "tree_sitter": TreeSitterTool(worktree_path),
            "repo_map": RepoMapTool(worktree_path),
            "simple_rag": SimpleRagTool(worktree_path),
            "lsp_symbols": LspSymbolsTool(worktree_path),
            "shell": ShellTool(worktree_path),
        }

    @classmethod
    def get_validator(cls, tool_name: str) -> "BaseToolValidator | None":
        """Return the validator instance for a tool, or None if not found."""
        if tool_name not in _VALIDATOR_MAP:
            return None
        module_path, class_name = _VALIDATOR_MAP[tool_name]
        try:
            mod = importlib.import_module(module_path)
            cls_ = getattr(mod, class_name)
            return cls_()
        except Exception as e:
            _log.warning("Failed to load validator for %s: %s", tool_name, e)
            return None

    @classmethod
    def get_all_validators(cls, tool_names: list[str]) -> list["BaseToolValidator"]:
        """Return validators for all specified tools (skips missing)."""
        result = []
        for name in tool_names:
            v = cls.get_validator(name)
            if v:
                result.append(v)
        return result
```

### 8.4 Update benchmark.py to use ToolRegistry

File: `src/orchestrator/benchmark.py`

Replace `_get_tools_for_config()` with:
```python
from src.features.tool_registry.registry import ToolRegistry

def _get_tools_for_config(self, config: Any, worktree_path: str) -> list[Any]:
    """Instantiate tools based on config using ToolRegistry."""
    full_map = ToolRegistry.build_tool_map(worktree_path)
    tools = []
    for t in config.tools:
        if t in full_map:
            try:
                tools.append(full_map[t])
            except Exception as e:
                self.logger.warning("Tool '%s' failed to initialize: %s", t, e)
        elif t not in ("serena", "semble"):  # MCP tools are handled separately
            self.logger.warning("Unknown tool '%s' in config %s", t, config.id)
    return tools
```

Remove all the individual tool imports from benchmark.py (they're now in ToolRegistry).

---

## Phase 9: ValidationPipeline

### 9.1 New directory and files

Create `src/features/validation/__init__.py` (empty).

### 9.2 New file: `src/features/validation/result.py`

```python
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class PhaseResult:
    tool_name: str
    phase: str
    passed: bool
    skipped: bool = False
    detail: str = ""


@dataclass
class ValidationReport:
    phase_results: list[PhaseResult] = field(default_factory=list)

    @property
    def all_critical_passed(self) -> bool:
        return all(r.passed or r.skipped for r in self.phase_results if r.phase in ("check_installed", "smoke_test"))

    def print_summary(self) -> None:
        from collections import defaultdict
        by_tool = defaultdict(list)
        for r in self.phase_results:
            by_tool[r.tool_name].append(r)
        
        print("\n" + "=" * 60)
        print("  VALIDATION PIPELINE REPORT")
        print("=" * 60)
        for tool_name, results in sorted(by_tool.items()):
            print(f"\n  Tool: {tool_name}")
            for r in results:
                status = "SKIP" if r.skipped else ("PASS" if r.passed else "FAIL")
                print(f"    [{status}] {r.phase}: {r.detail[:80]}")
        print("=" * 60)
        if self.all_critical_passed:
            print("  All critical checks passed.")
        else:
            print("  CRITICAL checks FAILED.")
        print("=" * 60 + "\n")
```

### 9.3 New file: `src/features/validation/pipeline.py`

```python
"""
ValidationPipeline: full tool validation pipeline.

Phases:
1. check_installed   — binary/package present?
2. install           — auto-install if missing
3. configure         — one-time setup (e.g. serena project.yml)
4. smoke_test        — basic functionality
5. validate_agno_registration — Agno agent sees tool
6. prepare           — expensive prep (RAG, repo map)
7. dry_run           — mock benchmark run

Usage:
    python -m src.features.validation.pipeline --tools rg,grep,shell --repo /path/to/repo
    python -m src.features.validation.pipeline --phase prepare --repo /path/to/repo
"""
from __future__ import annotations

import argparse
import logging
import os
import platform
import subprocess
import sys
import tempfile

from src.features.tool_registry.registry import ToolRegistry
from src.features.validation.result import PhaseResult, ValidationReport

_log = logging.getLogger(__name__)


def _detect_platform() -> str:
    if sys.platform == "win32":
        return "windows"
    # Check for WSL
    try:
        with open("/proc/version") as f:
            if "microsoft" in f.read().lower():
                return "wsl"
    except Exception:
        pass
    if sys.platform == "darwin":
        return "mac"
    return "linux"


class ValidationPipeline:
    """
    Runs validation phases for specified tools in order.
    """

    def __init__(
        self,
        tools: list[str],
        repo_path: str,
        phases: list[str] | None = None,
        auto_install: bool = False,
    ):
        self.tools = tools
        self.repo_path = repo_path
        self.phases = phases or ["check_installed", "smoke_test", "validate_agno_registration"]
        self.auto_install = auto_install
        self.platform = _detect_platform()
        self.validators = ToolRegistry.get_all_validators(tools)

    def run(self) -> ValidationReport:
        report = ValidationReport()

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create a minimal Python file for smoke tests
            test_file = os.path.join(tmp_dir, "test_smoke.py")
            with open(test_file, "w") as f:
                f.write("def hello_world():\n    pass\n\ndef test_something():\n    assert 1 == 1\n")

            # Init git in tmp_dir for git-based tools
            try:
                subprocess.run(["git", "init", "-q"], cwd=tmp_dir, capture_output=True)
                subprocess.run(["git", "config", "user.email", "v@test.com"], cwd=tmp_dir, capture_output=True)
                subprocess.run(["git", "config", "user.name", "Validator"], cwd=tmp_dir, capture_output=True)
                subprocess.run(["git", "add", "."], cwd=tmp_dir, capture_output=True)
                subprocess.run(["git", "commit", "-m", "init", "-q"], cwd=tmp_dir, capture_output=True)
            except Exception:
                pass

            for validator in self.validators:
                # Phase 1: check_installed
                if "check_installed" in self.phases:
                    result = validator.check_installed()
                    report.phase_results.append(PhaseResult(
                        tool_name=validator.tool_name,
                        phase="check_installed",
                        passed=result.passed,
                        detail=result.detail,
                    ))

                    # Phase 2: install if missing and auto_install enabled
                    if not result.passed and self.auto_install and "install" in self.phases:
                        install_result = validator.install(self.platform)
                        report.phase_results.append(PhaseResult(
                            tool_name=validator.tool_name,
                            phase="install",
                            passed=install_result.passed,
                            detail=install_result.detail,
                        ))
                        # Re-check
                        recheck = validator.check_installed()
                        if not recheck.passed:
                            _log.error("Tool %s still not available after install attempt.", validator.tool_name)
                            continue

                # Phase 3: configure
                if "configure" in self.phases:
                    config_result = validator.configure(self.repo_path)
                    report.phase_results.append(PhaseResult(
                        tool_name=validator.tool_name,
                        phase="configure",
                        passed=config_result.passed,
                        detail=config_result.detail,
                    ))

                # Phase 4: smoke_test
                if "smoke_test" in self.phases:
                    smoke_result = validator.smoke_test(tmp_dir)
                    report.phase_results.append(PhaseResult(
                        tool_name=validator.tool_name,
                        phase="smoke_test",
                        passed=smoke_result.passed,
                        detail=smoke_result.detail,
                    ))

                # Phase 5: Agno registration
                if "validate_agno_registration" in self.phases:
                    agno_result = validator.validate_agno_registration(tmp_dir)
                    report.phase_results.append(PhaseResult(
                        tool_name=validator.tool_name,
                        phase="validate_agno_registration",
                        passed=agno_result.passed,
                        detail=agno_result.detail,
                    ))

                # Phase 6: prepare (expensive — only when explicitly requested)
                if "prepare" in self.phases:
                    prep_result = validator.prepare(self.repo_path)
                    report.phase_results.append(PhaseResult(
                        tool_name=validator.tool_name,
                        phase="prepare",
                        passed=prep_result.passed,
                        detail=prep_result.detail,
                    ))

        report.print_summary()
        return report


def main():
    parser = argparse.ArgumentParser(description="Validation Pipeline for benchmark tools")
    parser.add_argument("--tools", default="all", help="Comma-separated tool names, or 'all'")
    parser.add_argument("--repo", required=True, help="Path to the target repository")
    parser.add_argument(
        "--phases", default="check_installed,smoke_test,validate_agno_registration",
        help="Comma-separated phases to run"
    )
    parser.add_argument("--auto-install", action="store_true", help="Auto-install missing tools")
    args = parser.parse_args()

    all_tools = list(ToolRegistry.build_tool_map(".").keys())
    tools = all_tools if args.tools == "all" else args.tools.split(",")
    phases = args.phases.split(",")

    pipeline = ValidationPipeline(
        tools=tools,
        repo_path=args.repo,
        phases=phases,
        auto_install=args.auto_install,
    )
    report = pipeline.run()
    sys.exit(0 if report.all_critical_passed else 1)


if __name__ == "__main__":
    main()
```

### 9.4 Integrate ValidationPipeline into PreflightChecker

File: `src/features/preflight.py`

Replace `_check_tool_cli_deps` and `_check_tool_smoke_tests` methods with a call to ValidationPipeline:

```python
def _check_via_validation_pipeline(self) -> list[PreflightResult]:
    """Run phases 1 and 4 (check_installed + smoke_test) via ValidationPipeline."""
    from src.features.validation.pipeline import ValidationPipeline
    
    needed_tools = set()
    for config in self.configs:
        needed_tools.update(config.tools)
    # Exclude MCP tools from preflight pipeline (they need target repo to run)
    needed_tools -= {"serena", "semble"}
    
    pipeline = ValidationPipeline(
        tools=list(needed_tools),
        repo_path=self.repo_path,
        phases=["check_installed", "smoke_test"],
        auto_install=False,
    )
    report = pipeline.run()
    
    results = []
    for pr in report.phase_results:
        level = "critical" if pr.phase == "check_installed" else "warning"
        results.append(PreflightResult(
            name=f"{pr.phase}: {pr.tool_name}",
            passed=pr.passed or pr.skipped,
            level=level,
            detail=pr.detail,
        ))
    return results
```

Update `run()` to call `_check_via_validation_pipeline()` instead of `_check_tool_cli_deps` and `_check_tool_smoke_tests` separately.

---

## Phase 10: Tests

### 10.1 Update `tests/features/test_patch.py`
Already described in Phase 1.1.

### 10.2 New file: `tests/features/test_cost_guard.py`

```python
import pytest
from src.features.cost_guard import CostGuard, BudgetExceededError


def test_suite_budget_not_exceeded():
    guard = CostGuard(max_suite_usd=5.0, max_config_usd=0.15, max_tokens_per_config=500_000)
    guard.check_suite_budget("config_01")  # should not raise


def test_suite_budget_exceeded():
    guard = CostGuard(max_suite_usd=0.10, max_config_usd=0.15, max_tokens_per_config=500_000)
    guard.record("c1", 0.12, 10000)
    with pytest.raises(BudgetExceededError):
        guard.check_suite_budget("c2")


def test_record_flags_cost_exceeded():
    guard = CostGuard(max_suite_usd=5.0, max_config_usd=0.10, max_tokens_per_config=500_000)
    flags = guard.record("c1", 0.20, 1000)
    assert flags["cost_exceeded"] is True
    assert flags["token_exceeded"] is False


def test_record_flags_token_exceeded():
    guard = CostGuard(max_suite_usd=5.0, max_config_usd=0.15, max_tokens_per_config=1000)
    flags = guard.record("c1", 0.05, 5000)
    assert flags["token_exceeded"] is True
    assert flags["cost_exceeded"] is False


def test_suite_summary():
    guard = CostGuard(max_suite_usd=5.0, max_config_usd=0.15, max_tokens_per_config=500_000)
    guard.record("c1", 0.05, 1000)
    guard.record("c2", 0.10, 2000)
    summary = guard.suite_summary
    assert summary["total_cost_usd"] == pytest.approx(0.15)
    assert summary["total_tokens"] == 3000
```

### 10.3 New file: `tests/features/test_execution_validator.py`

```python
import shutil
import subprocess
import pytest
from src.features.execution_validator import ExecutionValidator


@pytest.fixture
def temp_repo(tmp_path):
    git_cmd = shutil.which("git") or "git"
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "app.py").write_text("def hello():\n    pass\n")
    subprocess.run([git_cmd, "init"], cwd=repo_dir, capture_output=True)
    subprocess.run([git_cmd, "config", "user.email", "t@t.com"], cwd=repo_dir, capture_output=True)
    subprocess.run([git_cmd, "config", "user.name", "Test"], cwd=repo_dir, capture_output=True)
    subprocess.run([git_cmd, "add", "."], cwd=repo_dir, capture_output=True)
    subprocess.run([git_cmd, "commit", "-m", "init"], cwd=repo_dir, capture_output=True)
    return repo_dir


def test_no_changes_returns_not_verified(temp_repo):
    validator = ExecutionValidator(str(temp_repo))
    result = validator.validate(validation_cmd=None, test_cmd=None, baseline_pass_count=None)
    assert result.outcome == "not_verified"


def test_syntax_check_passes_valid_code(temp_repo):
    (temp_repo / "new_file.py").write_text("def add(a, b):\n    return a + b\n")
    validator = ExecutionValidator(str(temp_repo))
    result = validator.validate(validation_cmd=None, test_cmd=None, baseline_pass_count=None)
    assert result.outcome in ("not_verified",)  # no test files changed, just syntax check


def test_syntax_check_fails_invalid_code(temp_repo):
    (temp_repo / "bad.py").write_text("def broken(\n")
    validator = ExecutionValidator(str(temp_repo))
    result = validator.validate(validation_cmd=None, test_cmd=None, baseline_pass_count=None)
    assert result.outcome == "failed"
    assert "bad.py" in result.stderr
```

### 10.4 New file: `tests/features/test_tool_validators.py`

```python
import pytest
import tempfile
import subprocess
import shutil

from src.features.tool_registry.registry import ToolRegistry


def test_all_validators_loadable():
    """All validators in _VALIDATOR_MAP should be importable."""
    from src.features.tool_registry.registry import _VALIDATOR_MAP
    for tool_name, (module_path, class_name) in _VALIDATOR_MAP.items():
        v = ToolRegistry.get_validator(tool_name)
        assert v is not None, f"Validator for '{tool_name}' could not be loaded"
        assert v.tool_name == tool_name


def test_pure_python_tools_check_installed():
    """Pure Python tools (no CLI) should always pass check_installed."""
    pure_python_tools = ["read", "write", "glob", "insert_after", "tree_sitter", "repo_map", "simple_rag"]
    for tool_name in pure_python_tools:
        validator = ToolRegistry.get_validator(tool_name)
        if validator:
            result = validator.check_installed()
            assert result.passed, f"{tool_name} check_installed failed: {result.detail}"


@pytest.fixture
def tmp_git_repo(tmp_path):
    (tmp_path / "sample.py").write_text("def hello():\n    pass\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init", "-q"], cwd=tmp_path, capture_output=True)
    return tmp_path


def test_shell_validator_smoke(tmp_git_repo):
    validator = ToolRegistry.get_validator("shell")
    assert validator is not None
    result = validator.smoke_test(str(tmp_git_repo))
    assert result.passed, f"shell smoke test failed: {result.detail}"
```

---

## Execution Notes for Gemini

1. **Order of implementation:**
   - Phase 1 (fix broken tests + InsertAfterTool) FIRST — everything else depends on clean tests
   - Phase 2 (ExecutionValidator) — new file + update agno_runner
   - Phase 3 (shell/configs/instructions)
   - Phase 4 (isolation cleanup)
   - Phase 5 (CostGuard)
   - Phase 6 (run logging)
   - Phase 7 (deferred judge)
   - Phase 8 (validators + ToolRegistry)
   - Phase 9 (ValidationPipeline)
   - Phase 10 (tests)

2. **Do NOT break existing tests.** Run `uv run pytest tests/ -q --tb=short` after each phase.

3. **The existing tool implementation files** (`basic_tools.py`, `grep_tools.py`, etc.) must NOT be deleted. `validator.py` files import from them.

4. **For every `__init__.py` in new directories:** create as empty file.

5. **When updating `agno_runner.py`:**
   - Add `validation_cmd: str | None = None` and `baseline_pass_count: int | None = None` to `__init__`
   - Replace `_validate_run` completely
   - Update all callers inside the class

6. **For `benchmark.py`:**
   - Add baseline capture before the config loop in `run_suite()`
   - Pass `validation_cmd` and `baseline_pass_count` to `AgnoRunner` constructor
   - The `BenchmarkMeta.validation_cmd` comes from `meta.validation_cmd`

7. **After all changes, run:**
   ```bash
   UV_LINK_MODE=copy uv run pytest tests/ -q --tb=short
   ```
   All tests must pass. Fix any failures before declaring done.

8. **Verify the dry-run still works:**
   ```bash
   UV_LINK_MODE=copy uv run python main.py --dry-run --config-ids 01_cursor_like
   ```
