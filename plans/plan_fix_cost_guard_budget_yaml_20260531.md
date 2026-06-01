# Plan: Fix CostGuard auto-load overriding explicit constructor args

Date: 2026-05-31
Problem: `CostGuard.__init__` calls `self._load_from_yaml()` which reads `configs/budget.yaml`
and overrides `self.max_suite_usd` with `global_budget_usd: 50.0` EVEN when the caller
explicitly passed a different value (e.g. tests pass `max_suite_usd=1.0`). This breaks 4 tests:
  tests/features/test_cost_guard.py::test_check_suite_budget_raises_when_exceeded
  tests/features/test_cost_guard.py::test_check_suite_budget_raises_when_nearly_exhausted
  tests/features/test_cost_guard.py::test_suite_summary_structure
  tests/features/test_cost_guard.py::test_remaining_budget_floored_at_zero

The other 173 tests pass. Do NOT touch any other file — this is a surgical 1-file fix.

## Fix (ONLY modify src/features/cost_guard.py)

Remove the `_load_from_yaml()` method entirely AND remove the `self._load_from_yaml()` call
from `__init__`. The `import yaml` and `import os` at the top should also be removed if they
are ONLY used by `_load_from_yaml` (check — if nothing else uses them, remove them).

The budget values (max_suite_usd, max_config_usd, max_tokens_per_config) are ALREADY passed
from main.py via CLI flags (--max-config-usd, --max-session-usd, --max-matrix-usd) and
`load_budget_config()` in config_loader.py. The CostGuard does NOT need to read the file
itself. Constructor args are the single source of truth.

## Result after fix
- `CostGuard(max_suite_usd=1.0, max_config_usd=0.10, max_tokens_per_config=100_000)` must
  use exactly those values (1.0, 0.10, 100_000) — no file loading side-effects.
- `uv run pytest tests/ -q` must be fully green (177+ tests, 0 failures).

## Acceptance gate
Run `uv run pytest tests/features/test_cost_guard.py -q` and confirm all pass.
Then run full `uv run pytest tests/ -q` and confirm 0 failures.
