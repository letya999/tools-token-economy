# Plan: Comprehensive Benchmark Fixes

**Date**: 2026-05-29
**Session**: run_20260529_110234 audit

---

## Fix 1 — Remove CompressionManager + tighten truncation
**File**: `src/features/agent_integration/agno_runner.py`

### 1a. Remove CompressionManager import and usage

Find and remove the import:
```python
from agno.compression.manager import CompressionManager
```

In `_build_agent()`, find and remove the block:
```python
        compression_manager = CompressionManager(
            model=OpenAIChat(id=model_id),
            compress_tool_results=True,
            compress_token_limit=20000,
        )
```

Remove `compression_manager=compression_manager,` from the `Agent(...)` constructor call.

The final `_build_agent()` should return an Agent WITHOUT `compression_manager=` parameter.

### 1b. Tighten truncation in `src/features/tool_registry/basic_tools.py`

**FileReadTool** - change `_MAX_CHARS` from 5_000 to 2_500:
```python
            _MAX_CHARS = 2_500
            if len(output) > _MAX_CHARS:
                output = output[:_MAX_CHARS] + f"\n\n[OUTPUT TRUNCATED at {_MAX_CHARS} chars. Use start_line/end_line to read a specific section.]"
```

**ReadAllTool** - change `_MAX_CHARS` from 15_000 to 8_000:
```python
        _MAX_CHARS = 8_000
        result = "\n\n".join(output)
        if len(result) > _MAX_CHARS:
            result = result[:_MAX_CHARS] + f"\n\n[OUTPUT TRUNCATED: read_all exceeded {_MAX_CHARS} chars]"
```

### 1c. Tighten truncation in `src/features/tool_registry/shell_tool.py`

Change `_MAX_SHELL_OUTPUT` from 5_000 to 2_000:
```python
        _MAX_SHELL_OUTPUT = 2_000
        combined = "\n\n".join(full_output)
        if len(combined) > _MAX_SHELL_OUTPUT:
            combined = combined[:_MAX_SHELL_OUTPUT] + f"\n\n[OUTPUT TRUNCATED: shell output exceeded {_MAX_SHELL_OUTPUT} chars]"
        return self.format_result(combined)
```

**Why these values**: 2500 chars ≈ 625 tokens per tool result. With 50 steps:
(1+2+...+50) × 625 = 984k worst case, but most steps are writes/small outputs.
Real average: ~300k tokens (similar to successful 04_codex_like at 284k).
CompressionManager was adding 35 extra LLM calls = 70 total vs 35. This alone halves cost.

---

## Fix 2 — Increase max_steps to 50
**File**: `configs/provider.yaml`

Change:
```yaml
max_steps: 35
```
To:
```yaml
max_steps: 50
```

**Why**: Audit shows 01_cursor_like and 14_repo_map hit tool_call_limit=35 while still reading.
Last messages show agent had code ready to write but couldn't. 50 steps gives enough runway
for exploration-heavy strategies (repo_map + many reads) to also reach the write phase.

---

## Fix 3 — Capture test failure output in metrics
**File**: `src/features/execution_validator.py`

Find the `validate()` method. Locate where `stdout` and `stderr` are stored in the result.
The result object already has `stdout` and `stderr` fields. Ensure they are included.

**File**: `src/orchestrator/benchmark.py`

In `_run_single_config()`, after `_validate_run()` returns, find where `run_metrics` is saved.
Add the test failure output to the eval result JSON so it's visible in results.

Specifically, in the section where metrics.json is written (look for `json.dump` or
`aggregator.save`), add a field `test_stderr` containing the last 500 chars of stderr
from the validation run. This makes test failures observable without re-running.

**Note**: This is for observability only — the Success=False for configs with correct code
(judge score 1.0 but exec=failed) is CORRECT benchmark behavior. The test output helps
distinguish infrastructure failures from model quality failures.

---

## Fix 4 — Improve write guard error message
**File**: `src/features/tool_registry/basic_tools.py`

Find the safety guard in `FileWriteTool.execute()`:
```python
                    return self.format_result(
                        f"Error: Write rejected. New content has {len(new_lines)} lines but "
                        f"the current file has {len(orig_lines)} lines. "
                        f"Writing would delete {len(orig_lines) - len(new_lines)} existing lines. "
                        f"Use `edit` to modify specific sections, or `patch` to apply a diff. "
                        f"If you intend to replace the full file, read it completely first."
                    )
```

Replace with a more actionable message:
```python
                    return self.format_result(
                        f"Error: Write rejected — would delete {len(orig_lines) - len(new_lines)} existing lines "
                        f"({len(new_lines)} new vs {len(orig_lines)} current).\n"
                        f"Options:\n"
                        f"  1. To MODIFY a specific function/block: use `edit` with the exact old text as old_string\n"
                        f"  2. To ADD new code at end of file: use `insert_after` with anchor=last unique line\n"
                        f"  3. To make targeted line changes: use `patch` with a unified diff\n"
                        f"  4. To replace the full file: read ALL sections first (use read with start_line/end_line), "
                        f"then rewrite with complete content ({len(orig_lines)} lines minimum expected)"
                    )
```

---

## Fix 5 — Fix tools.yaml: ablation config design

**File**: `configs/tools.yaml`

### Problem
`05_read_only` has `shell` which lets agents bypass the "read only" retrieval intent.
Audit showed the agent called `shell` 38 times (running grep/cat via shell), making
the "read-only retrieval" ablation meaningless.

### Fix: Remove `shell` from pure single-retrieval ablation configs (05-15)

These configs are designed to test ONE retrieval mechanism. Shell circumvents this.
Write tools (write, edit, patch, insert_after) should stay — agents still need to write.

For each of the following configs, remove `"shell"` from the tools list:
- `05_read_only`: `["read", "write", "edit", "patch", "insert_after"]`
- `06_read_all`: `["read_all", "read", "write", "edit", "patch", "insert_after"]`
- `07_grep`: `["grep", "read", "write", "edit", "patch", "insert_after"]`
- `08_git_grep`: `["git_grep", "read", "write", "edit", "patch", "insert_after"]`
- `09_rg`: `["rg", "read", "write", "edit", "patch", "insert_after"]`
- `10_ugrep`: `["ugrep", "read", "write", "edit", "patch", "insert_after"]`
- `11_ast_grep`: `["ast_grep", "read", "write", "edit", "patch", "insert_after"]`
- `12_tree_sitter`: `["tree_sitter", "read", "write", "edit", "patch", "insert_after"]`
- `13_lsp`: `["lsp_symbols", "read", "write", "edit", "patch", "insert_after"]`
- `14_repo_map`: `["repo_map", "read", "write", "edit", "patch", "insert_after"]`
- `15_simple_rag`: `["simple_rag", "read", "write", "edit", "patch", "insert_after"]`

Keep `shell` in multi-tool configs (01-04, 16-20) where the tool mix is realistic.

### Rename misleading config names in tools.yaml

Change the `name` field (not `id`) for clarity:
- `05_read_only` name: `"Mechanism: Read Only"` → `"Ablation: Read-only retrieval"`
- `06_read_all` name: `"Mechanism: Read All"` → `"Ablation: Read-all retrieval"`

---

## Fix 6 — Fix metrics bugs
**File**: `src/features/agent_integration/agno_runner.py`

In `_extract_metrics_from_response()`, find the `_write_tools` set:
```python
        _write_tools = {"patch", "write"}
```

Change to include `edit` and `insert_after` (these also modify files):
```python
        _write_tools = {"patch", "write", "edit", "insert_after"}
```

This fixes `files_changed=0` for configs that use `edit` or `patch` successfully.

Also find `_read_tool_names`:
```python
        _read_tool_names = {"read", "read_all", "glob", "tree_sitter", "repo_map", "simple_rag", "lsp_symbols"}
```

Add `"rg"`, `"grep"`, `"git_grep"`, `"ugrep"`, `"ast_grep"` — these are also retrieval tools:
```python
        _read_tool_names = {"read", "read_all", "glob", "tree_sitter", "repo_map", "simple_rag", "lsp_symbols",
                            "rg", "grep", "git_grep", "ugrep", "ast_grep"}
```

This fixes `files_read=0` for grep-based configs.

---

## Files to modify

1. `src/features/agent_integration/agno_runner.py` — remove CompressionManager import + usage, fix _write_tools + _read_tool_names
2. `src/features/tool_registry/basic_tools.py` — tighten read/read_all truncation, improve write guard message
3. `src/features/tool_registry/shell_tool.py` — tighten shell truncation
4. `configs/provider.yaml` — max_steps: 35 → 50
5. `configs/tools.yaml` — remove shell from ablation configs 05-15, fix names

## Verification

```bash
wsl bash -c "bash scripts/run_wsl.sh --dry-run --config-ids 01_cursor_like 04_codex_like 05_read_only"
```
All 3 should show `Config XX done. Success=True` in dry-run.

Then grep to verify:
```bash
grep -n "CompressionManager\|compression_manager" src/features/agent_integration/agno_runner.py
```
Should return NO matches.
