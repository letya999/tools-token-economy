# Plan: Fix test_cmd uv environment and runner prefix extraction

## Problem
Running `uv run pytest tests/unit/ -x -q --timeout=60` fails because:
1. `pytest` is in `[project.optional-dependencies].dev`, NOT main deps.
2. `uv run pytest` without `--extra dev` falls back to system pytest at `/usr/local/bin/pytest`,
   which uses its own Python interpreter where `fastapi` is NOT installed.
3. Result: `ModuleNotFoundError: No module named 'fastapi'` in conftest.py.
4. Also: `--timeout=60` requires `pytest-timeout` plugin which is NOT in the target project's dev deps.
5. The runner prefix extraction in `_validate_run` breaks at the first `-` character, so
   `"uv run --extra dev pytest ..."` would yield `runner_parts = ["uv", "run"]` (missing pytest).

## Diagnosis confirmed
- `uv run python -c "import fastapi"` → works (uses venv python)
- `uv run pytest --version` → resolves to `/usr/local/bin/pytest` (system, wrong env)
- `uv run --extra dev pytest ...` → installs pytest into the project venv, uses correct Python → 11/11 pass

## Changes Required

### 1. `configs/benchmark_configs.yaml`
Change line:
```
test_cmd: "uv run pytest tests/unit/ -x -q --timeout=60"
```
To:
```
test_cmd: "uv run --extra dev pytest tests/unit/ -x -q"
```
Reason: `--extra dev` installs pytest into the isolated venv. Remove `--timeout=60` since
`pytest-timeout` is not listed in the target project's dev dependencies.

### 2. `src/features/agent_integration/agno_runner.py`
In method `_validate_run`, replace the runner prefix extraction block.

Current code (lines ~128-135):
```python
cmd_parts = shlex.split(test_cmd)
runner_parts = []
for part in cmd_parts:
    if part.startswith('-') or '/' in part or os.sep in part:
        break
    runner_parts.append(part)

specific_cmd = shlex.join(runner_parts + test_files + ["-x", "-q", "--timeout=60"])
```

New code:
```python
cmd_parts = shlex.split(test_cmd)
# Find 'pytest' token to preserve any preceding uv flags (e.g. --extra dev)
try:
    pytest_idx = next(i for i, p in enumerate(cmd_parts) if p in ('pytest', 'py.test'))
    runner_parts = cmd_parts[:pytest_idx + 1]
except StopIteration:
    # Fallback: stop before first flag or path argument
    runner_parts = []
    for part in cmd_parts:
        if part.startswith('-') or '/' in part or os.sep in part:
            break
        runner_parts.append(part)

specific_cmd = shlex.join(runner_parts + test_files + ["-x", "-q"])
```

Note: removed `--timeout=60` from hardcoded flags (not portable without pytest-timeout).

### 3. `tests/features/test_agno_runner_validation.py`
No changes needed. All four tests use `"pytest"` as the test_cmd directly:
- `runner._validate_run("/tmp/wt", "pytest")`
- `pytest_idx = 0`, `runner_parts = ["pytest"]` → correctly builds `pytest tests/test_main.py -x -q`
- The third subprocess mock still catches the EvalEngine subprocess call and returns the test output.

## Verification
After changes, run:
```
wsl -- bash -lc "cd /mnt/c/Users/User/a_projects/tools_token_economy && UV_PROJECT_ENVIRONMENT=/tmp/tte_venv uv run pytest tests/features/test_agno_runner_validation.py -v"
```
All 4 tests should pass.

Then run the full benchmark suite with:
```
wsl -- bash -lc "cd /mnt/c/Users/User/a_projects/tools_token_economy && UV_PROJECT_ENVIRONMENT=/tmp/tte_venv uv run python main.py --results results_real --worktree-base ../_oc_worktrees"
```
