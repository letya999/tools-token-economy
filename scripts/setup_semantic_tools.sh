#!/bin/bash
# Guaranteed install of semantic tool dependencies
# Run from WSL: bash scripts/setup_semantic_tools.sh
set -e

VENV_PYTHON="/mnt/c/Users/User/a_projects/tools_token_economy/.venv-wsl/bin/python"

echo "=== Installing semantic tool dependencies ==="

# 1. Serena MCP — needed for serena tool
if ! command -v serena &>/dev/null; then
    echo "Installing serena-agent..."
    $VENV_PYTHON -m pip install serena-agent
else
    echo "serena: OK ($(serena --version 2>/dev/null || echo installed))"       
fi

# 2. Qdrant client + fastembed — needed for simple_rag tool
echo "Installing qdrant-client and fastembed..."
$VENV_PYTHON -m pip install "qdrant-client>=1.9.0" "fastembed>=0.3.6"

# 3. Verify imports
$VENV_PYTHON -c "import qdrant_client; print('qdrant-client: OK', qdrant_client.__version__)"
$VENV_PYTHON -c "import fastembed; print('fastembed: OK', fastembed.__version__)"

echo "=== Semantic tool setup complete ==="
