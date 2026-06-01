# Plan: Fix 03_gemini_like and 06_read_all configs (TPM + context window overflow)

## Problem
Configs `03_gemini_like` and `06_read_all` both use the `read_all` tool which reads the ENTIRE
target repository and returns it as one big string. This generates 600k–1.5M tokens, which:
1. Exceeds gpt-4o-mini context window (128k tokens) → API rejects the request
2. Exceeds gpt-4o-mini TPM limit (200k/min) → rate limit errors

## Solution
Two complementary fixes:

### Fix 1: Change model for heavy configs
Switch `03_gemini_like` and `06_read_all` to `openai/gpt-4.1-mini` which has:
- 1M token context window (vs 128k)
- Higher TPM limits
- Cost: ~$0.40/$1.60 per 1M tokens (input/output) — still cheap

### Fix 2: Add character cap to ReadAllTool
Add a hard cap of 800,000 characters (~200k tokens) to `ReadAllTool.execute()`.
If the output exceeds the cap, truncate and append a clear message:
`"\n\n[TRUNCATED: output exceeded 800000 chars limit]"`
This is a safety net for very large repos and prevents unbounded output.

## Files to Modify

### 1. `configs/benchmark_configs.yaml`
For configs `03_gemini_like` and `06_read_all`, change:
```yaml
model: "openai/gpt-4o-mini"
```
to:
```yaml
model: "openai/gpt-4.1-mini"
```

Only these two configs need the change — all others keep `openai/gpt-4o-mini`.

### 2. `src/core/models.py`
Add pricing entries for gpt-4.1-mini. Find the `PRICING` dict (or equivalent) and add:
```python
"gpt-4.1-mini": {"input": 0.40, "output": 1.60},
"openai/gpt-4.1-mini": {"input": 0.40, "output": 1.60},
```
Units are USD per 1M tokens (same scale as existing entries).

### 3. `src/features/tool_registry/basic_tools.py`
In `ReadAllTool.execute()`, after building the full output string, add a truncation check:

Current code (end of execute method):
```python
        return self.format_result("\n\n".join(output))
```

Replace with:
```python
        _MAX_CHARS = 800_000
        result = "\n\n".join(output)
        if len(result) > _MAX_CHARS:
            result = result[:_MAX_CHARS] + "\n\n[TRUNCATED: output exceeded 800000 chars limit]"
        return self.format_result(result)
```

## Verification
After changes, confirm:
1. `configs/benchmark_configs.yaml` shows `gpt-4.1-mini` for configs 03 and 06 only
2. `src/core/models.py` has the new pricing entries
3. `src/features/tool_registry/basic_tools.py` has the truncation logic

Run tests to ensure nothing is broken:
```
wsl -- bash -lc "cd /mnt/c/Users/User/a_projects/tools_token_economy && UV_PROJECT_ENVIRONMENT=/tmp/tte_venv uv run pytest tests/ -x -q 2>&1 | tail -15"
```
