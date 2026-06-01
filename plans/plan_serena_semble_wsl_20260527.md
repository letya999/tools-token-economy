# Plan: Fix Serena and Semble as Working MCP Tools in WSL

## Diagnosis

Four confirmed problems that prevent Serena and Semble from working:

1. **`potion-code-16M` model incomplete** (FIXED manually — downloaded OK).
   - Blobs had `.incomplete` files; snapshot dir had only `.gitattributes`.
   - Downloaded successfully: `StaticModel dim: 256`.

2. **`preflight.py` checks wrong model for Semble** (BUG).
   - `_check_semble_embedding_model` imports `fastembed` + `BAAI/bge-small-en-v1.5`.
   - Semble uses `model2vec` + `minishlab/potion-code-16M` — completely different stack.
   - Preflight passes even when semble will fail at runtime.

3. **PATH not enriched for MCP subprocess env** (RISK).
   - `agno_runner.py` passes `env=os.environ.copy()` to `StdioServerParameters`.
   - If benchmark is started without `$HOME/.local/bin` in PATH (e.g. direct Python call),
     `serena` and `uvx` won't be found by the subprocess.
   - `shutil.which()` in preflight also won't find them.

4. **No actual MCP session test in preflight** (GAP).
   - Preflight only checks binary presence, not that MCP servers start and respond.

---

## Files to Modify

### `src/features/preflight.py`

Changes:
- Add `_wsl_path()` helper: returns PATH string with `~/.local/bin` and `~/.cargo/bin` prepended.
- Add `_wsl_which(binary)` helper: checks with extended PATH for WSL/Linux.
- Add `_enrich_path()` function that mutates `os.environ["PATH"]` in WSL.
- Call `_enrich_path()` at top of `PreflightChecker.run()`.
- In `_check_tool_cli_deps()`: replace `shutil.which(cli)` with `_wsl_which(cli)`.
- Replace `_check_semble_embedding_model()` entirely with correct implementation:
  - Check for `minishlab/potion-code-16M` in HF cache (`~/.cache/huggingface/hub/models--minishlab--potion-code-16M/snapshots/`)
  - A complete download has files beyond `.gitattributes` in the snapshot dir
  - If incomplete: clean `.incomplete` blobs, re-download via `uvx --from semble[mcp] python -c "from model2vec import StaticModel; StaticModel.from_pretrained('minishlab/potion-code-16M')"`
  - Timeout: 300s (model is ~25MB but CDN can be slow)
  - Level: `warning` (semble configs will fail but non-semble ones still run)
- Add `_check_serena_global_config()`:
  - Check `~/.serena/serena_config.yml` exists
  - If missing: run `serena init` or create minimal config
  - Level: `critical` if serena configs are active
- Add `_check_serena_mcp()` (optional, runs only if serena active):
  - Start serena MCP server against a temp dir with minimal project.yml
  - Verify it outputs the MCP initialization line within 10s
  - Level: `warning`
- Register new checks in `run()` check list.

### `src/features/agent_integration/agno_runner.py`

Changes:
- In `_run_with_mcp()`, before building `StdioServerParameters`:
  - Build `mcp_env = os.environ.copy()`
  - On non-Windows: prepend `~/.local/bin` and `~/.cargo/bin` to `mcp_env["PATH"]` if not already present
  - Use `mcp_env` instead of `os.environ.copy()` in `StdioServerParameters`

### `scripts/install/install_semble.sh`

Changes:
- Before model pre-load: delete any `.incomplete` blobs in the HF cache for `potion-code-16M`
- Add `touch ~/.semble_warmed_up` after successful model download

### `scripts/setup_tools/setup_serena_semble.sh`

Changes:
- Fix semble test command: use `semble "$SEMBLE_TMP"` not `semble mcp "$SEMBLE_TMP"` (no `mcp` subcommand)
- Fix semble version check: `semble --version` dispatches to MCP mode; use `uvx --from semble semble --help 2>&1 | grep -q semble` instead

---

## Implementation Notes

- Do NOT change the `McpServerConfig` command strings in `benchmark.py` — they are correct.
- Do NOT change any config YAML files.
- Do NOT touch `serena` validator — it works correctly.
- The `_check_tool_cli_deps` critical level should remain but use `_wsl_which`.
- Serena global config check: `~/.serena/serena_config.yml` must exist or Serena raises 14-field pydantic ValidationError on startup.
- The new semble model check replaces the old `_check_semble_embedding_model` entirely.
- Keep the check name `"Semble: embedding model"` → change to `"Semble: potion-code-16M model"`.
