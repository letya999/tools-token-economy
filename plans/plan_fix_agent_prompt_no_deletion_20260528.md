# Plan: Fix agent instructions to prevent deletion of existing code

## Problem
gpt-4.1-mini rewrites entire test files instead of adding a new test, deleting 9-20 existing tests.
Also: when serena/semble are active, the agent sometimes ignores them and falls back to plain read.

## Files to modify

### 1. `src/features/agent_integration/agno_runner.py` — `_build_agent()` method

Add two new instructions to the `instructions` list (lines 122-131):

```python
"CRITICAL: NEVER delete, truncate, or overwrite existing code. When adding to an existing file, preserve ALL existing content. If using 'write', copy all original content and append/insert only your new code. If using 'patch', only add lines — NEVER remove existing functions, classes, or tests.",
"CRITICAL: NEVER remove or replace existing tests. The test file already contains tests. You must ADD a new test without touching any existing test.",
```

These go AFTER the existing line:
```
"Never output TASK_COMPLETE if you have not called write or patch at least once.",
```

### 2. `src/features/prompt_builder.py` — serena instructions block

Change the serena block to be clearer that the agent must:
- Use `replace_symbol_body` or `insert_after_symbol` for surgical edits (NOT rewrite the whole file with `create_text_file`)
- Read the file first with `read_file` before modifying

Replace the serena block:
```python
    if "serena" in config.tools:
        lines.append(
            "\nIMPORTANT - HOW TO USE serena:\n"
            "Serena is an MCP tool that provides semantic code navigation.\n"
            "You MUST call serena tools (e.g. find_symbol, get_symbols_overview) to locate code.\n"
            "Do NOT fall back to the plain 'read' tool for navigation — use serena first.\n"
            "After finding the target with serena, use 'write' or 'patch' to save your changes."
        )
```

With:
```python
    if "serena" in config.tools:
        lines.append(
            "\nIMPORTANT - HOW TO USE serena:\n"
            "Serena MCP provides semantic code navigation. Use it as follows:\n"
            "1. Call find_symbol or get_symbols_overview to locate target code.\n"
            "2. Call read_file to read the existing file content.\n"
            "3. Use insert_after_symbol to ADD new code after an existing symbol.\n"
            "   OR use replace_symbol_body to REPLACE only the body of one symbol.\n"
            "   OR use write/patch if serena edit tools are unavailable.\n"
            "NEVER use create_text_file to overwrite an existing file — this deletes all existing content.\n"
            "NEVER delete existing tests or functions. Only ADD new code."
        )
```

And update the semble block similarly:
```python
    if "semble" in config.tools:
        lines.append(
            "\nIMPORTANT - HOW TO USE semble:\n"
            "Semble is a semantic search MCP tool. Call search() with a natural-language query\n"
            "to find the most relevant files and symbols.\n"
            "After semble returns results, use serena read_file (or plain read) to read the target file.\n"
            "Then use serena insert_after_symbol / replace_symbol_body — or write/patch — to ADD your changes.\n"
            "Do NOT skip semble when it is available — always search before editing."
        )
```

## After modifying files

Run configs 16, 17, 20 as a fresh full run (not retry-failed — use --config-ids):

```bash
wsl -e bash -c "cd /mnt/c/Users/User/a_projects/tools_token_economy && source .venv-wsl/bin/activate && python main.py --config-ids 16_serena_only 17_semble_only 20_serena_semble 2>&1"
```

Note: This starts a NEW benchmark run (new timestamp), not patching the existing 20260527_181911 run.
