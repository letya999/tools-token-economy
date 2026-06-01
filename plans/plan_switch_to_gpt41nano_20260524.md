# Plan: Switch 03/06 configs from gpt-4.1-mini to gpt-4.1-nano

## Decision
Research via web search confirmed gpt-4.1-nano is the cheapest OpenAI model with 1M context:
- gpt-4.1-nano: $0.10 input / $0.40 output per 1M tokens
- gpt-4.1-mini: $0.40 input / $1.60 output per 1M tokens (4x more expensive)
- Both have 1M token context window (sufficient for read_all configs)

## Changes Required

### 1. `configs/benchmark_configs.yaml`
For configs `03_gemini_like` and `06_read_all`, change:
```yaml
model: "openai/gpt-4.1-mini"
```
To:
```yaml
model: "openai/gpt-4.1-nano"
```

### 2. `src/core/models.py`
In the PRICING dict, replace the gpt-4.1-mini entries with gpt-4.1-nano entries:

Remove:
```python
"gpt-4.1-mini": {"input": 0.40, "output": 1.60},
"openai/gpt-4.1-mini": {"input": 0.40, "output": 1.60},
```

Add:
```python
"gpt-4.1-nano": {"input": 0.10, "output": 0.40},
"openai/gpt-4.1-nano": {"input": 0.10, "output": 0.40},
```

## Verification
After changes:
1. Check configs show `gpt-4.1-nano` for 03 and 06
2. Check models.py has correct nano pricing
3. Run tests: `wsl -- bash -lc "cd /mnt/c/Users/User/a_projects/tools_token_economy && UV_PROJECT_ENVIRONMENT=/tmp/tte_venv uv run pytest tests/ -x -q 2>&1 | tail -5"`
