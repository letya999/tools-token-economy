#!/usr/bin/env bash
# WSL benchmark runner — handles native venv and worktree paths.
# Usage: bash scripts/run_wsl.sh [--dry-run] [--config-ids ...] [--runs N] [...]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

NATIVE_VENV="/home/$(whoami)/.venvs/tools_token_economy"
NATIVE_WORKTREES="/home/$(whoami)/_oc_worktrees"

# Bootstrap native venv if it doesn't exist.
# Use uv venv + uv sync with explicit Python 3.13. NO UV_LINK_MODE=copy —
# venv is on native Linux fs, hardlinks work correctly and install all files.
if [ ! -d "$NATIVE_VENV" ]; then
    echo "[run_wsl] Creating native venv at $NATIVE_VENV..."
    uv venv --python 3.13 "$NATIVE_VENV"
    UV_PROJECT_ENVIRONMENT="$NATIVE_VENV" uv sync --project "$PROJECT_DIR"
fi

mkdir -p "$NATIVE_WORKTREES"

# Activate venv directly — do NOT export UV_PROJECT_ENVIRONMENT.
# Exporting UV_PROJECT_ENVIRONMENT causes ALL child uv subprocesses (including
# target repo uv sync in preflight/benchmark) to write into our venv, corrupting it.
source "$NATIVE_VENV/bin/activate"

exec python "$PROJECT_DIR/main.py" \
    --worktree-base "$NATIVE_WORKTREES" \
    "$@"
