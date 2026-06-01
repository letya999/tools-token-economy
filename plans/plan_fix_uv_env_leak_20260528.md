# Plan: Fix UV_PROJECT_ENVIRONMENT Leaking into Target Repo subprocess

**Date**: 2026-05-28  
**Priority**: CRITICAL — blocks correct operation of real benchmark runs

---

## Root Cause

`src/features/preflight.py::_run_uv_sync()` runs `uv sync` in the target repo directory.
The benchmark is launched via `run_wsl.sh` which exports `UV_PROJECT_ENVIRONMENT=/home/artem/.venvs/tools_token_economy`.

Since `subprocess.run()` inherits the parent process's environment, the target repo's `uv sync` uses `UV_PROJECT_ENVIRONMENT=/home/artem/.venvs/tools_token_economy` — overwriting the tools_token_economy venv with the target repo's venv (Python 3.12, process-metrics-platform).

This corrupts the running Python process's module lookup, causing all subsequent LLM Judge calls to fail with `[Errno 2] No such file or directory` (certifi CA bundle path changes from `python3.13` to `python3.12`).

The same issue exists in `benchmark.py::_setup_target_repo()` which also runs `uv sync` in the target repo.

---

## Files to Modify

### 1. `src/features/preflight.py` — `_run_uv_sync` method (~line 492)

**Current code**:
```python
def _run_uv_sync(self) -> PreflightResult:
    extras = self._extract_uv_extras()
    cmd = ["uv", "sync"]
    for extra in extras:
        cmd += ["--extra", extra]
    _log.info("Running `%s` in target repo: %s", " ".join(cmd), self.repo_path)
    try:
        proc = subprocess.run(
            cmd,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
```

**Fixed code** — strip `UV_PROJECT_ENVIRONMENT` and `UV_LINK_MODE` from subprocess env so the target repo creates its own venv:
```python
def _run_uv_sync(self) -> PreflightResult:
    extras = self._extract_uv_extras()
    cmd = ["uv", "sync"]
    for extra in extras:
        cmd += ["--extra", extra]
    _log.info("Running `%s` in target repo: %s", " ".join(cmd), self.repo_path)
    # Remove UV_PROJECT_ENVIRONMENT so target repo creates its own venv,
    # not reusing the benchmark's venv.
    env = os.environ.copy()
    env.pop("UV_PROJECT_ENVIRONMENT", None)
    env.pop("UV_LINK_MODE", None)
    try:
        proc = subprocess.run(
            cmd,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
```

### 2. `src/orchestrator/benchmark.py` — `_setup_target_repo` method (~line 112)

Same fix: strip `UV_PROJECT_ENVIRONMENT` from subprocess environment.

**Current code**:
```python
def _setup_target_repo(self, repo_path: str, test_cmd: str) -> None:
    """Ensure target repo is installed and importable before benchmark starts."""
    self.logger.info("Running `uv sync --extra dev` in target repo: %s", repo_path)
    result = subprocess.run(
        ["uv", "sync", "--extra", "dev"],
        cwd=repo_path, capture_output=True, text=True, timeout=300
    )
```

**Fixed code**:
```python
def _setup_target_repo(self, repo_path: str, test_cmd: str) -> None:
    """Ensure target repo is installed and importable before benchmark starts."""
    self.logger.info("Running `uv sync --extra dev` in target repo: %s", repo_path)
    # Strip UV_PROJECT_ENVIRONMENT so target repo gets its own venv.
    env = os.environ.copy()
    env.pop("UV_PROJECT_ENVIRONMENT", None)
    env.pop("UV_LINK_MODE", None)
    result = subprocess.run(
        ["uv", "sync", "--extra", "dev"],
        cwd=repo_path, capture_output=True, text=True, timeout=300,
        env=env,
    )
```

---

## Also: Rebuild venv correctly after fix

After applying the fix, the benchmark's venv at `/home/artem/.venvs/tools_token_economy` needs to be rebuilt with Python 3.13 (it was overwritten with Python 3.12):

```bash
rm -rf /home/artem/.venvs/tools_token_economy
UV_PROJECT_ENVIRONMENT=/home/artem/.venvs/tools_token_economy UV_LINK_MODE=copy uv sync --project /mnt/c/Users/User/a_projects/tools_token_economy
```

---

## Execution Order

1. Fix `src/features/preflight.py` — `_run_uv_sync`
2. Fix `src/orchestrator/benchmark.py` — `_setup_target_repo`
3. Both changes are minimal: add `env = os.environ.copy(); env.pop(...); env.pop(...)` and pass `env=env` to subprocess.run

---

## Validation

After fix: run `bash scripts/run_wsl.sh --dry-run --config-ids 01_cursor_like` and verify:
- venv at `/home/artem/.venvs/tools_token_economy/pyvenv.cfg` shows Python 3.13 AFTER the run
- `prompt = tools-token-economy` (not `process-metrics-platform`)
