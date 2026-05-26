#!/bin/bash
# Install native Linux node.js (LTS) + npm + npx.
# Primary: nvm (no sudo required). Fallback: NodeSource apt repo (needs sudo).
set -e

# 1. Ensure nvm is available.
if [ ! -s "$HOME/.nvm/nvm.sh" ]; then
    echo "[node] Installing nvm..."
    NVM_LATEST="$(curl -fsSL https://api.github.com/repos/nvm-sh/nvm/releases/latest \
        | grep '"tag_name"' | cut -d'"' -f4)"
    curl -fsSL "https://raw.githubusercontent.com/nvm-sh/nvm/${NVM_LATEST}/install.sh" | bash
fi
source "$HOME/.nvm/nvm.sh"

# 2. Install node LTS via nvm (no sudo, installs to ~/.nvm/versions/node/).
if ! nvm ls --no-colors 2>/dev/null | grep -q "lts/"; then
    echo "[node] Installing node LTS via nvm..."
    nvm install --lts
fi
nvm use --lts

# Verify all three binaries resolve to Linux paths (not /mnt/c).
for bin in node npm npx; do
    path="$(command -v "$bin" 2>/dev/null)"
    if [[ -z "$path" || "$path" == /mnt/* ]]; then
        echo "[node] WARN: $bin not found via nvm, falling back to apt..." >&2
        # Fallback: apt (requires sudo — may fail in non-interactive shells).
        if command -v curl &>/dev/null; then
            curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
        fi
        sudo apt-get install -y nodejs
        break
    fi
done

echo "[node] node: $(node --version)"
echo "[node] npm:  $(npm --version)"
echo "[node] npx:  $(npx --version)"
echo "[node] nvm:  $(nvm --version)"
