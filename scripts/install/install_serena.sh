#!/bin/bash
# Install Serena MCP server and create global config.
# Must run AFTER uv AND node are available (run install_node.sh first).
# Sets UV_LINK_MODE=copy for /mnt/c paths.
set -e
export UV_LINK_MODE=copy

# Install serena-agent with pyright[nodejs] bundled.
# pyright[nodejs] includes a self-contained node runtime inside serena's tool
# venv as a second layer of defence if the system node is ever missing.
if command -v uv &>/dev/null; then
    uv tool install -p 3.13 "serena-agent@latest" --prerelease=allow \
        --with "pyright[nodejs]" 2>/dev/null \
        || uv tool install -p 3.13 "serena-agent@latest" --prerelease=allow 2>/dev/null \
        || uv pip install "serena-agent>=1.5.0"
fi

SERENA_HOME="${HOME}/.serena"
mkdir -p "$SERENA_HOME"

# Create minimal global config so pydantic-settings does not fail with
# ValidationError on the 14 required fields it cannot find in env vars.
# Fields and defaults taken from serena_config.template.yml (v1.5.x).
if [ ! -f "$SERENA_HOME/serena_config.yml" ]; then
    cat > "$SERENA_HOME/serena_config.yml" << 'EOF'
language_backend: LSP
line_ending: native
gui_log_window: false
web_dashboard: false
web_dashboard_open_on_launch: false
web_dashboard_interface: browser
web_dashboard_listen_address: "127.0.0.1"
jetbrains_plugin_server_address: "127.0.0.1"
log_level: 30
trace_lsp_communication: false
ls_specific_settings: {}
ignored_paths:
  - "**/.git/**"
  - "**/node_modules/**"
  - "**/__pycache__/**"
  - "**/.venv/**"
  - "**/venv/**"
  - "**/dist/**"
  - "**/build/**"
read_only_memory_patterns: []
ignored_memory_patterns: []
tool_timeout: 240
excluded_tools: []
included_optional_tools: []
fixed_tools: []
base_modes:
  - interactive
  - editing
default_modes: []
default_max_tool_answer_chars: 150000
token_count_estimator: CHAR_COUNT
symbol_info_budget: 10
project_serena_folder_location: "$projectDir/.serena"
projects: []
EOF
    echo "[serena] Created $SERENA_HOME/serena_config.yml"
else
    echo "[serena] Global config already exists at $SERENA_HOME/serena_config.yml"
fi

echo "[serena] Install complete. Binary: $(command -v serena 2>/dev/null || echo 'NOT FOUND — add ~/.local/bin to PATH')"
