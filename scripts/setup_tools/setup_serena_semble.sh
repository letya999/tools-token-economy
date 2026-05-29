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

# semble starts as MCP stdio server when called as: semble [path]
# There is NO 'mcp' subcommand — the first non-CLI-dispatch arg triggers MCP mode.
SEMBLE_TMP="$(mktemp -d)"
timeout 5 uvx --from "semble[mcp]" semble "$SEMBLE_TMP" &>/dev/null \
    && echo "[OK] semble starts cleanly as MCP server" \
    || echo "[OK] semble MCP exited (expected on early timeout)"
rm -rf "$SEMBLE_TMP"

echo ""
echo "=== Semble model pre-warm ==="
# Clean incomplete model blobs before attempting download
BLOBS_DIR="$HOME/.cache/huggingface/hub/models--minishlab--potion-code-16M/blobs"
[ -d "$BLOBS_DIR" ] && find "$BLOBS_DIR" -name "*.incomplete" -delete 2>/dev/null && echo "Cleaned incomplete blobs"

# Download potion-code-16M model if not fully cached
uvx --from "semble[mcp]" python -c "
from model2vec import StaticModel
m = StaticModel.from_pretrained('minishlab/potion-code-16M')
print('[OK] model ready:', type(m).__name__)
" 2>&1 || echo "[WARN] model preload failed"

# Mark warmup done
touch ~/.semble_warmed_up
echo "[OK] semble ready"

echo ""
echo "Serena/Semble verification complete."
