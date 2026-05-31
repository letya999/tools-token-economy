# Windows native benchmark runner.
# Usage: .\scripts\run_windows.ps1 [--dry-run] [--config-ids ...] [--runs N] [...]
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir

# On Windows, uv needs copy mode for NTFS hardlink operations.
$env:UV_LINK_MODE = "copy"

# Run the benchmark using uv (handles venv automatically).
& uv run --project $ProjectDir python "$ProjectDir\main.py" @Args
