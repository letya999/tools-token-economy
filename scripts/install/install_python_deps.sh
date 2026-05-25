#!/bin/bash
set -e
export UV_LINK_MODE=copy
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"
UV_PROJECT_ENVIRONMENT=.venv-wsl uv sync
