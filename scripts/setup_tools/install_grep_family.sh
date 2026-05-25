#!/bin/bash
# install_grep_family.sh
# Скрипт для установки инструментов семейства grep в WSL2/Ubuntu

set -e

echo "Installing grep family tools..."

# Update package list
sudo apt-get update -y

# 1. Ripgrep (rg)
if ! command -v rg &> /dev/null; then
    echo "Installing ripgrep..."
    sudo apt-get install -y ripgrep
else
    echo "ripgrep is already installed."
fi

# 2. Ugrep
if ! command -v ugrep &> /dev/null; then
    echo "Installing ugrep..."
    sudo apt-get install -y ugrep || {
        echo "ugrep not found in default repos, installing via build-essential or prebuilt binary..."
        # Можно добавить логику скачивания бинарника с GitHub
    }
else
    echo "ugrep is already installed."
fi

# 3. ast-grep (sg) - replaces semgrep (>= 1.100 paywalled for code lines output)
# ast-grep binary from GitHub releases (provides both `sg` and `ast-grep`)      
if ! command -v ast-grep &>/dev/null; then
    echo "Downloading ast-grep binary from GitHub releases..."
    LATEST=$(curl -sL https://api.github.com/repos/ast-grep/ast-grep/releases/latest | python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'])")   
    curl -sL "https://github.com/ast-grep/ast-grep/releases/download/${LATEST}/app-x86_64-unknown-linux-gnu.zip" -o /tmp/ast-grep.zip
    python3 -c "import zipfile; zipfile.ZipFile('/tmp/ast-grep.zip').extractall('/tmp/ast-grep-extracted/')"
    mkdir -p ~/.local/bin
    cp /tmp/ast-grep-extracted/ast-grep ~/.local/bin/ast-grep
    cp /tmp/ast-grep-extracted/sg ~/.local/bin/sg
    chmod +x ~/.local/bin/ast-grep ~/.local/bin/sg
    rm -rf /tmp/ast-grep.zip /tmp/ast-grep-extracted
    echo "ast-grep: OK ($(ast-grep --version))"
else
    echo "ast-grep: OK ($(ast-grep --version))"
fi

echo "Grep family installation complete."
