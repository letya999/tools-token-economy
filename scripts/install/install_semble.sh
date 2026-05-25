#!/bin/bash
uv tool install "semble[mcp]"
uvx --from "semble[mcp]" semble --help || true
