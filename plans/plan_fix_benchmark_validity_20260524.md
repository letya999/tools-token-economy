# Plan: Fix Benchmark Validity

**Date:** 2026-05-24  
**Goal:** Make success detection real — not string-match, but actual test results + non-empty git diff.

---

## Problems to Fix

1. `success = "TASK_COMPLETE" in content_str` — fake success, model says it without changing files
2. `tests_passed=0` always — test tool is `None`, never runs
3. `patch_lines=0` always — counter never updated
4. `gpt-4o-mini` missing from pricing table → wrong cost estimate
5. `success=True` hardcoded in `EvalResult` in `run_suite` (cosmetic, but misleading)

---

## Files to Modify

### 1. `src/features/agent_integration/agno_runner.py`

**Add post-run validation method `_validate_run(worktree_path, test_cmd)`:**
- Run `git diff --name-only HEAD` in `worktree_path` via subprocess
- Parse output to get list of changed files
- Filter changed files to test files only: files matching `tests/` prefix or `test_*.py` / `*_test.py` pattern
- If no test files changed → `success = False`, `tests_passed = 0`
- If test files changed → run ONLY those specific test files:
  ```
  uv run pytest <file1> <file2> -x -q --timeout=60
  ```
  in `worktree_path` via subprocess with `cwd=worktree_path`
- Parse pytest exit code: 0 = passed, else failed
- Parse pytest stdout for `N passed` pattern → set `tests_passed = N`
- Return `(success: bool, tests_passed: int, patch_lines: int)`

**Update `run()` method:**
- After `agent.run()` call, call `_validate_run(worktree_path, test_cmd)` instead of checking `TASK_COMPLETE`
- Set `success`, `tests_passed`, `patch_lines` from validation result
- Keep `TASK_COMPLETE` check only as fallback when `worktree_path` not provided (backward compat)

**Signature change for `run()`:**
```python
def run(self, task_description: str, worktree_path: str = ".", test_cmd: str = "uv run pytest") -> RunMetrics:
```

**Fix `patch_lines` counter:**
- After agent run, count lines in `git diff HEAD` output via subprocess:
  ```python
  diff_output = subprocess.run(["git", "diff", "HEAD"], cwd=worktree_path, capture_output=True, text=True)
  patch_lines = len([l for l in diff_output.stdout.splitlines() if l.startswith('+') or l.startswith('-')])
  ```

### 2. `src/orchestrator/benchmark.py`

**Pass `test_cmd` to `AgnoRunner.run()`:**
- `BenchmarkOrchestrator.__init__` already accepts `test_cmd` via `**_kwargs` — expose it as `self.test_cmd`
- In `run_suite`, pass `test_cmd=self.test_cmd` and `worktree_path=worktree_path` to `runner.run()`

**Fix hardcoded `success=True` in `EvalResult`:**
```python
final_result = EvalResult(
    run_id=run_id,
    config_id=config.id,
    metrics=run_metrics,
    success=run_metrics.success,  # use actual success from runner
    error=None,
    patch=None,
)
```

### 3. `src/core/models.py`

**Add `gpt-4o-mini` to pricing table in `RunMetrics.cost_usd`:**
```python
"gpt-4o-mini": {"input": 0.15, "output": 0.60},
"openai/gpt-4o-mini": {"input": 0.15, "output": 0.60},
```

---

## Key Design Decisions

- **Run only changed test files** (not full suite): `git diff --name-only HEAD | grep -E 'test_.*\.py|.*_test\.py'`
- **If agent wrote no test files → failure** (task was to add tests)
- **Subprocess calls use `cwd=worktree_path`** so they run in the isolated worktree
- **Timeout**: use existing `self.timeout_sec` for subprocess calls
- **No breaking changes to `RunMetrics` schema** — `tests_passed`, `patch_lines`, `files_changed` already exist

---

## Tests to Update

### `tests/orchestrator/test_benchmark.py`
- Update `test_orchestrator_dry_run_runs_all_configs` — dry run still uses mock, no change needed
- Add test: `test_orchestrator_passes_test_cmd_to_runner` — verify `test_cmd` propagated

### `tests/features/test_shell.py` or new `tests/features/test_agno_runner_validation.py`
- Test `_validate_run` with mocked subprocess: empty diff → success=False
- Test `_validate_run` with mocked subprocess: test file changed + pytest passes → success=True, tests_passed=N
- Test `_validate_run` with mocked subprocess: test file changed + pytest fails → success=False

---

## What NOT to Change

- Mock/dry-run path in `_run_mock` — keeps returning `success=True` for dry runs (correct)
- `_build_agno_tools` — `WARNING: Failed to add validate decorator` is an Agno internals issue, not in scope
- `tool_map["test"] = None` in benchmark.py — `test` tool is now replaced by post-run validation, keep as None
- Any result files in `results/` — only new runs will use the new logic
