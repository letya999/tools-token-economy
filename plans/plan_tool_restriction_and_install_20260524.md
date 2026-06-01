# Plan: Fix tool restriction prefix + install missing WSL tools

## Problem 1: Tool restriction prefix never applied

`build_tool_restriction_prefix(config)` exists in `src/features/opencode_config.py` but is NEVER called in `src/orchestrator/benchmark.py`. All 20 benchmark configs receive identical prompts — the entire point of the benchmark (comparing tool combinations) is broken.

### Fix: `src/orchestrator/benchmark.py`

1. Add import at top: `from src.features.opencode_config import write_opencode_json, build_tool_restriction_prefix`
   (Currently only `write_opencode_json` is imported)

2. In `run_suite`, before calling `runner.run(...)`, prepend the tool restriction prefix:
   ```python
   prefix = build_tool_restriction_prefix(config)
   full_task = (prefix + task_description) if prefix else task_description
   run_metrics = runner.run(full_task, worktree_path=worktree_path)
   ```
   Replace the current line:
   ```python
   run_metrics = runner.run(task_description, worktree_path=worktree_path)
   ```

## Problem 2: ugrep and semgrep missing from WSL

Configs `10_ugrep` and `11_semgrep` require these tools to be physically installed in WSL Ubuntu so opencode can call them via bash.

### Fix: `scripts/setup_wsl.sh`

Add installation steps after the existing git/opencode/uv setup:

```bash
# 5. Benchmark tool dependencies
# ugrep - fast grep alternative
if ! command -v ugrep &>/dev/null; then
  sudo apt-get install -y ugrep 2>/dev/null || {
    # Fallback: install from GitHub releases if not in apt
    UGREP_VER="7.3.2"
    wget -q "https://github.com/Genivia/ugrep/releases/download/v${UGREP_VER}/ugrep_${UGREP_VER}_amd64.deb" -O /tmp/ugrep.deb
    sudo dpkg -i /tmp/ugrep.deb && rm /tmp/ugrep.deb
  }
fi

# semgrep - semantic grep for code patterns
if ! command -v semgrep &>/dev/null; then
  pip install semgrep --quiet
fi
```

### Fix: Also run installation NOW in WSL (separate from script update)

Since setup_wsl.sh is for fresh installs, we also need to install these immediately:
- `sudo apt-get install -y ugrep` (or from .deb if not in apt)
- `pip install semgrep` in WSL

## Files to modify

1. `src/orchestrator/benchmark.py` — add tool restriction prefix to task description
2. `scripts/setup_wsl.sh` — add ugrep and semgrep installation steps

## Verification

After changes:
- Run `uv run pytest tests/orchestrator/test_benchmark.py -x -q` to verify benchmark tests still pass
- Confirm `build_tool_restriction_prefix` is now imported and called
- The prompt sent to opencode for config `10_ugrep` should contain "[BENCHMARK TOOL CONFIG]" header

## Note on implementation order

1. First fix `benchmark.py` (code change, no WSL needed)
2. Then update `scripts/setup_wsl.sh`  
3. Then run WSL installation commands for ugrep/semgrep
