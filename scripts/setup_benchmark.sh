#!/bin/bash
set -e
export PATH="$HOME/.local/bin:$PATH"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

check_and_install() {
    local CHECK="$SCRIPT_DIR/checks/$1"
    local INSTALL="$SCRIPT_DIR/install/$2"
    local TOOL="$3"

    if bash "$CHECK" 2>/dev/null; then
        echo "  [OK] $TOOL"
        return 0
    fi

    echo "  [MISSING] $TOOL — installing..."
    bash "$INSTALL"

    if bash "$CHECK" 2>/dev/null; then
        echo "  [OK] $TOOL — installed successfully"
        return 0
    fi

    echo "  [FATAL] $TOOL — still missing after install. Check logs above." >&2
    exit 1
}

export VENV_PYTHON="${VENV_PYTHON:-$SCRIPT_DIR/../.venv-wsl/bin/python}"

echo ""
echo "=== [1/3] CLI tool checks & installs ==="
check_and_install check_git.sh       install_git.sh       "git"
check_and_install check_uv.sh        install_uv.sh        "uv/uvx"
check_and_install check_rg.sh        install_rg.sh        "ripgrep (rg)"
check_and_install check_ugrep.sh     install_ugrep.sh     "ugrep"
check_and_install check_astgrep.sh   install_astgrep.sh   "ast-grep"
check_and_install check_serena.sh    install_serena.sh    "serena MCP server"
check_and_install check_semble.sh    install_semble.sh    "semble MCP server"
check_and_install check_python_deps.sh install_python_deps.sh "Python packages"

echo ""
echo "=== [2/3] Python-level smoke tests ==="
$VENV_PYTHON scripts/verify/verify_basic_tools.py
$VENV_PYTHON scripts/verify/verify_grep_tools.py
$VENV_PYTHON scripts/verify/verify_rag_tool.py

echo ""
echo "=== [3/3] MCP server + Agno integration verification ==="
$VENV_PYTHON scripts/verify/verify_serena_mcp_fixed.py
$VENV_PYTHON scripts/verify/verify_semble_mcp.py

echo ""
echo "All checks passed. Environment is ready for benchmark."
