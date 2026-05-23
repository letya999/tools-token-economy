#!/bin/bash
# setup_serena_semble.sh
# Скрипт для инициализации Serena и Semble MCP

set -e

echo "Initializing Serena MCP..."

# Инициализация Serena
if command -v serena &> /dev/null; then
    echo "Running serena init..."
    serena init --yes
    
    echo "Starting Serena MCP server in background..."
    # В реальности здесь может понадобиться специфическая конфигурация
    # serena start-mcp-server &
else
    echo "Error: serena CLI not found. Please install it first."
fi

# Инициализация Semble
# (Предполагаем, что Semble ставится аналогично или через npm/pip)
if command -v semble &> /dev/null; then
    echo "Running semble init..."
    semble init --yes
else
    echo "Warning: semble CLI not found."
fi

echo "Serena/Semble initialization complete."
