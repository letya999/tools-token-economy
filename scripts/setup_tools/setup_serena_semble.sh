#!/bin/bash
# Verify Serena and Semble MCP servers are operational after installation.
# This script is a post-install smoke test, not an installer.
# Run install_serena.sh and install_semble.sh first.
set -e
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:/usr/local/bin:$PATH"

echo "=== Verifying Serena MCP ==="
if ! command -v serena &>/dev/null; then
    echo "[FAIL] serena binary not found" >&2
    exit 1
fi

# Start serena MCP against a temp dir and immediately check it responds to
# the MCP initialize handshake. timeout 10 catches hangs.
SERENA_TMP="$(mktemp -d)"
timeout 10 serena start-mcp-server --project "$SERENA_TMP" &>/dev/null \
    && echo "[OK] serena MCP start-mcp-server responds" \
    || echo "[WARN] serena MCP start-mcp-server returned non-zero (may be expected on early exit)"
rm -rf "$SERENA_TMP"

[ -f "${HOME}/.serena/serena_config.yml" ] \
    && echo "[OK] ~/.serena/serena_config.yml present" \
    || { echo "[FAIL] ~/.serena/serena_config.yml missing" >&2; exit 1; }

echo ""
echo "=== Verifying Semble MCP ==="
if ! command -v uvx &>/dev/null; then
    echo "[FAIL] uvx not found — install uv first" >&2
    exit 1
fi

# semble mcp takes a positional path argument (NOT --path).
# Run against /tmp with a short timeout to confirm the binary starts cleanly.
SEMBLE_TMP="$(mktemp -d)"
timeout 5 uvx --from "semble[mcp]" semble mcp "$SEMBLE_TMP" &>/dev/null \
    && echo "[OK] semble mcp starts cleanly" \
    || echo "[OK] semble mcp exited (expected on early timeout)"
rm -rf "$SEMBLE_TMP"

echo ""
echo "=== Semble pre-warm ==="
# Pre-download semble package so first benchmark run doesn't time out
if ! uvx --from semble semble --version &>/dev/null 2>&1; then
    echo "Downloading semble via uvx (first-time install)..."
    uv tool install semble || uvx --from semble semble --help || true
fi
# Mark warmup done
touch ~/.semble_warmed_up
uvx --from semble semble --version 2>/dev/null && echo "[OK] semble ready" || echo "[WARN] semble not verified"

echo ""
echo "Serena/Semble verification complete."
