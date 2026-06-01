# Plan: WSL Environment Fixes for Benchmark

**Date**: 2026-05-28  
**Goal**: Fix WSL-specific bugs and infrastructure issues found during preflight/dry-run. Then the real benchmark can be launched reliably.

---

## Issues Found

### Bug 1 — Wrong string literal in `_make_isolation_provider` (benchmark.py:46)
`repo_path.startswith("\mnt\")` uses Python escape sequences that produce `\mnt\` (backslash-m, nt, backslash).  
This NEVER matches `/mnt/c/...` paths. The condition is always False on WSL.  
**Impact**: WSL-aware isolation path never activates; worktrees default to /mnt/c which is slow.

### Bug 2 — `setup_wsl.sh` creates venv on /mnt/c
Lines 27-29 of `scripts/setup_wsl.sh`:
```bash
export UV_LINK_MODE=copy
uv venv --python 3.13
uv sync
```
`uv venv` without `UV_PROJECT_ENVIRONMENT` creates `.venv` in the current directory (which is `/mnt/c/...`).  
This causes I/O errors (os error 5) on Windows NTFS symlinks and corrupts packages like `jedi`, `httpcore`.

### Missing — No WSL run wrapper script
Users must manually set `UV_PROJECT_ENVIRONMENT`, `UV_LINK_MODE`, and `--worktree-base` each time.  
Error-prone and inconsistent.

---

## Files to Modify

### 1. `src/orchestrator/benchmark.py` (lines 45-48)
Fix the backslash bug and improve the isolation provider selection logic.

**Current code**:
```python
def _make_isolation_provider(repo_path: str, worktree_base: str):
    if sys.platform != "win32" and repo_path.startswith("\mnt\"):
        return DirectCopyIsolationProvider(repo_path, "/tmp/benchmark_runs")
    return GitIsolationProvider(repo_path, worktree_base)
```

**Fixed code**:
```python
def _make_isolation_provider(repo_path: str, worktree_base: str):
    # When repo is on /mnt/ (Windows FS mounted in WSL) and worktree_base is native Linux,
    # GitIsolationProvider creates lightweight worktrees on fast native fs.
    # DirectCopyIsolationProvider is only used when git is unavailable.
    return GitIsolationProvider(repo_path, worktree_base)
```

The `DirectCopyIsolationProvider` branch was unreachable (backslash bug) and hardcoded a bad path (`/tmp/benchmark_runs`). `GitIsolationProvider` with a native `worktree_base` is better: lightweight checkout, fast teardown.

### 2. `scripts/setup_wsl.sh` (lines 25-29)
Fix venv creation to use native WSL filesystem.

**Current code**:
```bash
# UV_LINK_MODE=copy required: venv lives on Windows NTFS (/mnt/c), hardlinks
# across Linux/NTFS boundaries fail and the fallback corrupts large packages (jedi, etc.)
export UV_LINK_MODE=copy
uv venv --python 3.13
uv sync
```

**Fixed code**:
```bash
# Venv must live on native Linux fs to avoid NTFS I/O errors.
# UV_LINK_MODE=copy needed because pyproject.toml is on /mnt/c (Windows FS).
NATIVE_VENV="/home/$(whoami)/.venvs/tools_token_economy"
mkdir -p "$(dirname "$NATIVE_VENV")"
export UV_PROJECT_ENVIRONMENT="$NATIVE_VENV"
export UV_LINK_MODE=copy
uv sync
```

Remove the `uv venv` call - `uv sync` creates the venv automatically using `UV_PROJECT_ENVIRONMENT`.

Also update the final echo to show the correct run command:
```bash
echo "Setup complete."
echo "Run: UV_PROJECT_ENVIRONMENT=$NATIVE_VENV UV_LINK_MODE=copy uv run python main.py --worktree-base /home/\$(whoami)/_oc_worktrees [args]"
echo "Or use: bash scripts/run_wsl.sh [args]"
```

### 3. `scripts/run_wsl.sh` (NEW FILE)
Create a wrapper script that handles all WSL-specific env setup.

```bash
#!/usr/bin/env bash
# WSL benchmark runner — handles native venv and worktree paths.
# Usage: bash scripts/run_wsl.sh [--dry-run] [--config-ids ...] [--runs N] [...]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

NATIVE_VENV="/home/$(whoami)/.venvs/tools_token_economy"
NATIVE_WORKTREES="/home/$(whoami)/_oc_worktrees"

# Bootstrap native venv if it doesn't exist
if [ ! -d "$NATIVE_VENV" ]; then
    echo "[run_wsl] Creating native venv at $NATIVE_VENV..."
    UV_PROJECT_ENVIRONMENT="$NATIVE_VENV" UV_LINK_MODE=copy uv sync --project "$PROJECT_DIR"
fi

export UV_PROJECT_ENVIRONMENT="$NATIVE_VENV"
export UV_LINK_MODE=copy

mkdir -p "$NATIVE_WORKTREES"

exec uv run --project "$PROJECT_DIR" python "$PROJECT_DIR/main.py" \
    --worktree-base "$NATIVE_WORKTREES" \
    "$@"
```

Make it executable (chmod +x).

---

## Execution Order

1. Modify `src/orchestrator/benchmark.py` — fix `_make_isolation_provider`
2. Modify `scripts/setup_wsl.sh` — fix venv creation
3. Create `scripts/run_wsl.sh` — new wrapper script

---

## Validation

After fixes, verify with:
```bash
wsl -e bash -lc "bash /mnt/c/Users/User/a_projects/tools_token_economy/scripts/run_wsl.sh --dry-run --config-ids 01_cursor_like"
```

Expected: config 01 completes with Success=True, no httpcore error, worktrees at `/home/artem/_oc_worktrees/`.
