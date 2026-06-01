# Plan: Fix 5 Failing Unit Tests

## Context
Two divergences between implementation and tests:

### Fix 1 — `tests/features/test_agno_runner_validation.py` (4 tests)
`AgnoRunner._validate_run()` now returns a 6-tuple:
`(success, tests_passed, tests_failed, patch_lines, execution_result, made_changes)`

Four tests still unpack only 4 values:
```python
success, tests_passed, tests_failed, patch_lines = runner._validate_run("/tmp/wt", "pytest")
```

**Change:** In all four test functions (`test_validate_run_no_changes`, `test_validate_run_no_test_files`,
`test_validate_run_test_passed`, `test_validate_run_test_failed`), replace the 4-value unpack with:
```python
success, tests_passed, tests_failed, patch_lines, *_ = runner._validate_run("/tmp/wt", "pytest")
```
Only the unpack line changes — all assertions remain identical.

### Fix 2 — `tests/features/test_metrics_aggregator.py` (1 test)
`RunMetrics.success_per_token` was changed (F-016) to return `1_000_000 / total_tokens` instead of `1.0 / total_tokens`.

`test_save_run_computes_success_per_token` still asserts the old value:
```python
assert data["success_per_token"] == pytest.approx(1.0 / 1000)   # 0.001 — WRONG
```

**Change:** Update to match current formula:
```python
assert data["success_per_token"] == pytest.approx(1_000_000.0 / 1000)   # 1000.0
```

## Files to modify
1. `tests/features/test_agno_runner_validation.py` — 4 lines changed (unpack only)
2. `tests/features/test_metrics_aggregator.py` — 1 line changed (expected value only)

## Verification
After the fix, run:
```
uv run pytest tests/features/test_agno_runner_validation.py tests/features/test_metrics_aggregator.py -v
```
All 5 previously-failing tests should pass. No other tests should regress.
