# Plan: Simplify Task + Raise max_steps and Budget Limits

**Date**: 2026-05-29

**Why**: Audit showed all 11 completed configs returned Success=False because:
1. `max_steps=15` is too low — agent exhausts all calls on reads, writes are blocked
2. Task is too complex (8 endpoints + Streamlit + tests = 35+ tool calls minimum)
3. CostGuard limits ($0.10/config, $2.00 suite) abort configs before completion

---

## Change 1 — `configs/benchmark_task.yaml`

Replace the entire `task.description` block with a simpler but still meaningful task.
The new task must NOT mention specific file paths, function names, or where to look.
The agent must discover the codebase structure itself.

Find the `task:` section. Replace the `description:` value with:

```yaml
task:
  description: |
    Add schedule and sensor management to the admin API.

    The application already has a Dagster-based pipeline system with schedules and sensors.
    The admin API currently has job management endpoints. Extend it by adding:

    1. Endpoints to list all Dagster schedules with their current running status
    2. Endpoints to start and stop individual schedules by name
    3. Endpoints to list all Dagster sensors with their current running status
    4. Endpoints to start and stop individual sensors by name

    Follow the existing patterns in the codebase for authentication, error handling,
    and response formatting. Add at least one unit test for the new functionality.

    You MUST use write or patch to save changes to disk. Reading without writing is a failure.
    When done, output exactly: TASK_COMPLETE

  test_cmd: "python -m pytest tests/unit/ -v --tb=short -q"

  success_criteria:
    - "New schedule and sensor endpoints are present in the codebase"
    - "At least one new unit test added"
    - "Existing tests still pass"
```

Keep all other fields in the file (target_repo, setup, etc.) unchanged.

---

## Change 2 — `configs/provider.yaml`

Change `max_steps` from 15 to 35.

Find:
```yaml
max_steps: 15
```

Replace with:
```yaml
max_steps: 35
```

---

## Change 3 — `src/orchestrator/benchmark.py`

Raise CostGuard defaults.

Find the CostGuard initialization block (around line 101-105):
```python
        self.cost_guard = CostGuard(
            max_suite_usd=_kwargs.get("max_suite_usd", 2.0),
            max_config_usd=_kwargs.get("max_config_usd", 0.10),
            max_tokens_per_config=_kwargs.get("max_tokens_per_config", 150_000),
        )
```

Replace with:
```python
        self.cost_guard = CostGuard(
            max_suite_usd=_kwargs.get("max_suite_usd", 8.0),
            max_config_usd=_kwargs.get("max_config_usd", 0.40),
            max_tokens_per_config=_kwargs.get("max_tokens_per_config", 600_000),
        )
```

---

## Files to modify

1. `configs/benchmark_task.yaml` — simplified task description (no file hints), simpler test_cmd
2. `configs/provider.yaml` — max_steps: 15 → 35
3. `src/orchestrator/benchmark.py` — CostGuard: suite $2→$8, config $0.10→$0.40, tokens 150k→600k

## Verification

After changes, run:
```
wsl bash -c "bash /mnt/c/Users/User/a_projects/tools_token_economy/scripts/run_wsl.sh --dry-run --config-ids 01_cursor_like"
```
Should print: `Config 01_cursor_like done. Success=True`
