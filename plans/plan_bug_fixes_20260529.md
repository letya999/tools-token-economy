# Plan: Fix 2 bugs introduced in agno_runner.py
**Date:** 2026-05-29
**Scope:** surgical 2-file fix only

---

## Bug 1: BudgetExceededError causes Pydantic ValidationError crash

**File:** `src/features/agent_integration/agno_runner.py`

**Root cause:**
In both `run()` and `_run_with_mcp()`, when `BudgetExceededError` is caught, the handler sets:
```python
metrics_data["execution_result"] = "budget_exceeded"
```
Then at the end of the method, the RunMetrics constructor uses:
```python
**(metrics_data or {fallback_dict})
```
When `metrics_data = {"execution_result": "budget_exceeded"}`, it is truthy, so the `or` fallback is NEVER used.
But `metrics_data` is missing required fields: `input_tokens`, `output_tokens`, `tool_tokens`, `model_calls`, `tool_calls`.
This causes a Pydantic `ValidationError` crash when constructing `RunMetrics`.

**Fix:**
Change the RunMetrics construction at the end of BOTH `_run_with_mcp()` AND `run()` methods.
Replace:
```python
**(metrics_data or {
    "input_tokens": 0, "output_tokens": 0, "tool_tokens": 0,
    "model_calls": 0, "tool_calls": 0, "files_read": 0,
    "files_changed": 0, "patch_lines": 0, "errors": 0, "tool_errors": 0,
    "tests_passed": 0, "execution_result": "not_verified", "made_changes": False,
}),
```
With:
```python
**{
    "input_tokens": 0, "output_tokens": 0, "tool_tokens": 0,
    "model_calls": 0, "tool_calls": 0, "files_read": 0,
    "files_changed": 0, "patch_lines": 0, "errors": 0, "tool_errors": 0,
    "tests_passed": 0, "execution_result": "not_verified", "made_changes": False,
    **metrics_data,  # override defaults with actual values if present
},
```

This pattern (defaults + override with actual) ensures:
- Normal case: all fields from `metrics_data` override defaults correctly
- BudgetExceededError case: defaults provide required fields, `execution_result` is overridden
- Empty metrics_data `{}`: all defaults used → no crash

Do this change in BOTH locations in agno_runner.py:
1. End of `_run_with_mcp()` method (the `return RunMetrics(...)` at the bottom)
2. End of `run()` method (the `return RunMetrics(...)` at the bottom)

---

## Bug 2: execution_result="telemetry_corrupt" gets overwritten

**File:** `src/features/agent_integration/agno_runner.py`

**Root cause:**
In `_extract_metrics_from_response()`, when phantom tokens are detected:
```python
metrics_data["execution_result"] = "telemetry_corrupt"
```
But then in BOTH `_run_with_mcp()` and `run()`, after `_validate_run()` is called:
```python
metrics_data["execution_result"] = exec_result  # overwrites "telemetry_corrupt"!
```

**Fix:**
In BOTH `_run_with_mcp()` and `run()`, after calling `_validate_run()`, only update `execution_result` if it was not already set to `"telemetry_corrupt"`:

Find these lines (there are 2 copies, one in each method):
```python
success, tests_passed, tests_failed, patch_lines, exec_result, made_changes, test_stderr = self._validate_run(worktree_path, test_cmd)
metrics_data["tests_passed"] = tests_passed
metrics_data["patch_lines"] = patch_lines
metrics_data["errors"] = tests_failed
metrics_data["execution_result"] = exec_result
metrics_data["made_changes"] = made_changes
metrics_data["test_stderr"] = test_stderr[-500:] if test_stderr else ""
```

Replace the `metrics_data["execution_result"] = exec_result` line with:
```python
if metrics_data.get("execution_result") != "telemetry_corrupt":
    metrics_data["execution_result"] = exec_result
```

Do this change in BOTH locations (in `_run_with_mcp` and in `run()`).

---

## Summary

Only `src/features/agent_integration/agno_runner.py` needs to be modified.
4 targeted line changes total.

After editing, run:
```bash
wsl bash -c "export PATH=\"\$HOME/.local/bin:\$HOME/.cargo/bin:/usr/local/bin:\$PATH\" && cd /mnt/c/Users/User/a_projects/tools_token_economy && UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=~/.eval_venvs/toolsecon uv run pytest tests/ -q --tb=short 2>&1 | tail -10"
```
All tests must still pass.
