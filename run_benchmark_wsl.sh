#!/bin/bash
set -e
export PATH="$HOME/.local/bin:$PATH"
export UV_LINK_MODE=copy
VENV_PYTHON="/mnt/c/Users/User/a_projects/tools_token_economy/.venv-wsl/bin/python"
export VENV_PYTHON
source /mnt/c/Users/User/a_projects/tools_token_economy/.venv-wsl/bin/activate
cd /mnt/c/Users/User/a_projects/tools_token_economy

echo "================================================================"
echo " BENCHMARK SETUP: check → install → verify → test → dry-run → run"
echo "================================================================"

echo ""
echo "=== [1/5] Environment setup (check, install, verify) ==="
bash scripts/setup_benchmark.sh

echo ""
echo "=== [2/5] Benchmark test suite ==="
$VENV_PYTHON -m pytest tests/ -q --tb=short

echo ""
echo "=== [3/5] Full preflight dry-run ==="
$VENV_PYTHON main.py --dry-run

echo ""
echo "=== [4/5] Running benchmark ==="
exec $VENV_PYTHON main.py
