#!/usr/bin/env bash
# WSL setup for tools_token_economy benchmark
# Run from WSL: bash scripts/setup_wsl.sh
set -e

# 1. Node / OpenCode
if ! command -v npm &>/dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi
if ! command -v opencode &>/dev/null; then
  curl -fsSL https://opencode.ai/install | bash
  # Ensure opencode is available in the current shell
  if [ -f ~/.bashrc ]; then
    source ~/.bashrc
  fi
fi

# 2. Python env (uv)
if ! command -v uv &>/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
# UV_LINK_MODE=copy required: venv lives on Windows NTFS (/mnt/c), hardlinks
# across Linux/NTFS boundaries fail and the fallback corrupts large packages (jedi, etc.)
export UV_LINK_MODE=copy
uv venv --python 3.13
uv sync

# 3. Serena MCP server (installs global binary + creates ~/.serena/serena_config.yml)
bash scripts/install/install_serena.sh

# 4. Clone target repo
# Note: repos should be in WSL native filesystem for best performance
REPO_DIR="${REPO_DIR:-$HOME/repos/benchmark_repo}"
mkdir -p "$(dirname "$REPO_DIR")"
if [ ! -d "$REPO_DIR" ]; then
  git clone https://github.com/letya999/process_metrics_platform_v2 "$REPO_DIR" 
fi

# 5. Benchmark tool dependencies
# ugrep - fast grep alternative
if ! command -v ugrep &>/dev/null; then
  sudo apt-get install -y ugrep 2>/dev/null || {
    # Fallback: install from GitHub releases if not in apt
    UGREP_VER="7.3.2"
    wget -q "https://github.com/Genivia/ugrep/releases/download/v${UGREP_VER}/ugrep_${UGREP_VER}_amd64.deb" -O /tmp/ugrep.deb
    sudo dpkg -i /tmp/ugrep.deb && rm /tmp/ugrep.deb
  }
fi

# ast-grep (sg) - free structural code search, replaces semgrep (paywalled >= 1.100)
# Installed via uv/pip from pyproject.toml - available in .venv/bin/sg after uv sync

# 6. Env check
if [ -z "$GOOGLE_API_KEY" ]; then
  echo "WARNING: GOOGLE_API_KEY is not set. Add to ~/.bashrc: export GOOGLE_API_KEY=your-key"
fi

echo "Setup complete. Run: source .venv/bin/activate"
echo "Then: python main.py --repo $REPO_DIR --task '...' --results results_real"
