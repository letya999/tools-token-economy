#!/bin/bash
# Two conditions must hold:
#   1. serena binary is in PATH
#   2. ~/.serena/serena_config.yml exists (prevents pydantic-settings ValidationError)
command -v serena &>/dev/null || exit 1
[ -f "${HOME}/.serena/serena_config.yml" ] || exit 1
