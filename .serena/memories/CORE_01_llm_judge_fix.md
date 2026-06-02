# LLM Judge Bug Fix (2026-06-02)

## Problem
Judge returned score=0.0 for all 126 runs due to AttributeError.

## Root Cause
In `src/features/llm_judge.py`, `_call_model()`:
- Code accessed `resp.metrics.input_tokens` — WRONG
- `ModelResponse` from Agno has NO `.metrics` field
- Tokens are in `resp.response_usage` (MessageMetrics object)
- `except (TypeError, ValueError)` did NOT catch AttributeError

## Fix Applied
```python
# Before (broken):
try:
    itok = int(getattr(resp.metrics, "input_tokens", 0) or 0)
except (TypeError, ValueError):
    itok = 0

# After (fixed):
try:
    usage = getattr(resp, "response_usage", None)
    if usage is not None:
        itok = int(getattr(usage, "input_tokens", 0) or 0)
    else:
        itok = int(getattr(resp, "input_tokens", 0) or 0)
except (TypeError, ValueError, AttributeError):
    itok = 0
```

## Agno API Note
- `model.response(msgs)` returns a single `ModelResponse`
- Tokens populated by `_parse_provider_response()` into `response_usage: MessageMetrics`
- `ModelResponse.input_tokens` is `Optional[int] = None` — NOT populated by the parser
