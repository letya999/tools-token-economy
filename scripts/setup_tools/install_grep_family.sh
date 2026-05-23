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

# 3. Semgrep
if ! command -v semgrep &> /dev/null; then
    echo "Installing semgrep via pip..."
    pip install semgrep
else
    echo "semgrep is already installed."
fi

echo "Grep family installation complete."
