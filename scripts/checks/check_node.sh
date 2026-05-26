#!/bin/bash
# Check that native Linux node, npm, and npx are available.
# Sources nvm.sh first so nvm-managed binaries are on the PATH.
# Windows binaries on /mnt/c are NOT acceptable — they don't work in WSL processes.

[ -s "$HOME/.nvm/nvm.sh" ] && source "$HOME/.nvm/nvm.sh"

_require_linux_bin() {
    local bin="$1"
    local path
    path="$(command -v "$bin" 2>/dev/null)" || return 1
    # Reject Windows-side binaries (paths under /mnt/)
    [[ "$path" == /mnt/* ]] && return 1
    return 0
}

_require_linux_bin node && \
_require_linux_bin npm  && \
_require_linux_bin npx
