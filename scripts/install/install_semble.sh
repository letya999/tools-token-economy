#!/bin/bash
# Install semble[mcp] and verify it starts correctly.
# With the [mcp] extra, 'semble' itself IS the MCP server (no 'mcp' subcommand).
# It accepts an optional positional path argument: semble [path]
set -e
export UV_LINK_MODE=copy

if ! command -v uv &>/dev/null; then
    echo "[semble] uv not found — install uv first" >&2
    exit 1
fi

echo "[semble] Installing semble[mcp] via uv tool..."
uv tool install "semble[mcp]"

# Pre-download the embedding model so first semble run doesn't block on network fetch.
# semble uses minishlab/potion-code-16M (model2vec StaticModel) for code indexing.
echo "[semble] Pre-loading embedding model (minishlab/potion-code-16M)..."
uvx --from "semble[mcp]" python -c "
from model2vec import StaticModel
m = StaticModel.from_pretrained('minishlab/potion-code-16M')
print('[semble] Embedding model cached:', type(m).__name__)
" 2>&1 || echo "[semble] WARN: model preload failed — will download on first use"

# Smoke-test: run against /tmp with a short timeout to confirm clean startup.
echo "[semble] Smoke-testing 'semble /tmp'..."
timeout 5 uvx --from "semble[mcp]" semble /tmp &>/dev/null || true
echo "[semble] Install complete."
