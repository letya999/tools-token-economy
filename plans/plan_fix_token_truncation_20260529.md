# Plan: Fix Token Truncation Limits and Compression Threshold

**Date**: 2026-05-29
**Problem**: CompressionManager triggers every 2-3 turns because truncation limits are too large.
Each tool call returns 5k-12k tokens, so after 2 calls the context already exceeds 6000 tokens.
Each compression = an extra LLM call with the full context → doubles token usage.

**Root cause analysis**:
- `read` → 20,000 chars = ~5,000 tokens per file read
- `shell` → 15,000 chars = ~3,750 tokens per command  
- After just 2 reads: context = ~10,000 tokens > 6,000 threshold → compression triggers
- Compression call itself costs ~10,000 tokens → net overhead, not savings

**Target state**:
- Each tool result: max ~1,250 tokens (5,000 chars)
- Compression threshold: 20,000 tokens (triggers only after many large calls)
- Per-config budget should stay within 150k tokens

---

## Change 1 — `src/features/tool_registry/basic_tools.py`

### `FileReadTool.execute()` — reduce `_MAX_CHARS` from 20,000 to 5,000

Find:
```python
            _MAX_CHARS = 20_000
            if len(output) > _MAX_CHARS:
                output = output[:_MAX_CHARS] + f"\n\n[OUTPUT TRUNCATED: file read exceeded {_MAX_CHARS} chars]"
```

Replace with:
```python
            _MAX_CHARS = 5_000
            if len(output) > _MAX_CHARS:
                output = output[:_MAX_CHARS] + f"\n\n[OUTPUT TRUNCATED: file read exceeded {_MAX_CHARS} chars. Use start_line/end_line to read specific sections.]"
```

### `ReadAllTool.execute()` — reduce `_MAX_CHARS` from 50,000 to 15,000

Find:
```python
        _MAX_CHARS = 50_000
        result = "\n\n".join(output)
        if len(result) > _MAX_CHARS:
            result = result[:_MAX_CHARS] + f"\n\n[OUTPUT TRUNCATED: read_all exceeded {_MAX_CHARS} chars]"
```

Replace with:
```python
        _MAX_CHARS = 15_000
        result = "\n\n".join(output)
        if len(result) > _MAX_CHARS:
            result = result[:_MAX_CHARS] + f"\n\n[OUTPUT TRUNCATED: read_all exceeded {_MAX_CHARS} chars]"
```

---

## Change 2 — `src/features/tool_registry/shell_tool.py`

### Reduce `_MAX_SHELL_OUTPUT` from 15,000 to 5,000

Find:
```python
        _MAX_SHELL_OUTPUT = 15_000
        combined = "\n\n".join(full_output)
        if len(combined) > _MAX_SHELL_OUTPUT:
            combined = combined[:_MAX_SHELL_OUTPUT] + f"\n\n[OUTPUT TRUNCATED: shell output exceeded {_MAX_SHELL_OUTPUT} chars]"
        return self.format_result(combined)
```

Replace with:
```python
        _MAX_SHELL_OUTPUT = 5_000
        combined = "\n\n".join(full_output)
        if len(combined) > _MAX_SHELL_OUTPUT:
            combined = combined[:_MAX_SHELL_OUTPUT] + f"\n\n[OUTPUT TRUNCATED: shell output exceeded {_MAX_SHELL_OUTPUT} chars]"
        return self.format_result(combined)
```

---

## Change 3 — `src/features/agent_integration/agno_runner.py`

### Raise `compress_token_limit` from 6,000 to 20,000

Find in `_build_agent()`:
```python
        compression_manager = CompressionManager(
            model=OpenAIChat(id=model_id),
            compress_tool_results=True,
            compress_token_limit=6000,
        )
```

Replace with:
```python
        compression_manager = CompressionManager(
            model=OpenAIChat(id=model_id),
            compress_tool_results=True,
            compress_token_limit=20000,
        )
```

With 5,000 char / ~1,250 token tool results, the context needs 16+ tool calls to reach 20,000 tokens.
At max_steps=15, compression rarely triggers → no compression overhead.

---

## Change 4 — `AGENTS.md` (update run instructions)

The AGENTS.md currently says to use `uv run python main.py`, but the correct WSL runner is
`scripts/run_wsl.sh` which handles UV_PROJECT_ENVIRONMENT isolation (prevents target repo's
`uv sync` from overwriting the benchmark's native venv).

Find the Phase 1 section:
```
### Phase 1 — Setup (run once, or after environment changes)
```bash
wsl bash -c "cd /mnt/c/Users/User/a_projects/tools_token_economy && uv run python main.py --setup"
```

Replace with:
```
### Phase 1 — Setup (run once, or after environment changes)
```bash
wsl bash -c "bash /mnt/c/Users/User/a_projects/tools_token_economy/scripts/run_wsl.sh --setup"
```

Find the Phase 2 section:
```
### Phase 2 — Run benchmark
```bash
wsl bash -c "cd /mnt/c/Users/User/a_projects/tools_token_economy && uv run python main.py"
```

Replace with:
```
### Phase 2 — Run benchmark
```bash
wsl bash -c "bash /mnt/c/Users/User/a_projects/tools_token_economy/scripts/run_wsl.sh"
```

**Why**: `scripts/run_wsl.sh` creates the venv on native Linux FS (`~/.venvs/tools_token_economy`)
and uses `source activate` instead of `uv run`, preventing UV_PROJECT_ENVIRONMENT from leaking
into target repo's `uv sync` subprocess calls.

---

## Expected outcome

With 5,000 char tool outputs (~1,250 tokens each):
- 15 turns × average 7,500 tokens per turn = ~112,500 total tokens
- At $0.40/M input: ~$0.045 per config → well within $0.10 budget
- CompressionManager rarely triggers (context stays below 20k tokens)

## Files to modify

1. `src/features/tool_registry/basic_tools.py` — read: 20k→5k, read_all: 50k→15k
2. `src/features/tool_registry/shell_tool.py` — shell: 15k→5k
3. `src/features/agent_integration/agno_runner.py` — compress_token_limit: 6k→20k
4. `AGENTS.md` — update run commands to use scripts/run_wsl.sh
