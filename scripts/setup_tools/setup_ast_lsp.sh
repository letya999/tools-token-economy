#!/bin/bash
# setup_ast_lsp.sh
# Скрипт для настройки Tree-sitter и LSP серверов

set -e

echo "Setting up AST and LSP tools..."

# 1. Tree-sitter CLI
if ! command -v tree-sitter &> /dev/null; then
    echo "Installing tree-sitter-cli via npm..."
    npm install -g tree-sitter-cli
fi

# 2. Python LSP (Pyright)
if ! command -v pyright &> /dev/null; then
    echo "Installing pyright via npm..."
    npm install -g pyright
fi

# 3. Python LSP Server (pylsp)
if ! command -v pylsp &> /dev/null; then
    echo "Installing python-lsp-server via pip..."
    pip install python-lsp-server
fi

echo "AST and LSP setup complete."
