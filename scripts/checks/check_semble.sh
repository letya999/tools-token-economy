#!/bin/bash
command -v uvx &>/dev/null || exit 1
uvx --from "semble[mcp]" semble --help &>/dev/null
