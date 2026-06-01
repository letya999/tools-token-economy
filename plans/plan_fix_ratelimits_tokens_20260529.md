# Plan: Fix Rate Limits, Token Overuse, and Budget Controls

**Date**: 2026-05-29  
**Goal**: Prevent TPM 429 errors and runaway token usage so all 20 benchmark configs complete within $2 total.

---

## Changes Required

### 1. `configs/provider.yaml` — Reduce max_steps

Change `max_steps: 50` to `max_steps: 15`.

This sets `tool_call_limit=15` in the Agno agent, preventing agents from making 30-50 tool calls per config. A coding task (find file → read → write → verify) needs at most 10-12 tool calls. 15 is a safe upper bound.

**Current:**
```yaml
max_steps: 50
```
**New:**
```yaml
max_steps: 15
```

---

### 2. `src/features/tool_registry/basic_tools.py` — Truncate `read_all` output

The `ReadAllTool.execute()` method reads all files and returns their concatenated content. This produced 2.6M tokens in one config run. Add a hard character limit of 50,000 characters on the output, with a clear truncation notice.

Find the `ReadAllTool` class (or equivalent `read_all` tool implementation). In its `execute()` or `format_result()` call, truncate the combined output string to 50_000 characters before returning. Append a message like `\n[OUTPUT TRUNCATED at 50000 chars]` if truncation occurred.

Also truncate the `ReadTool` (single file read) to 20_000 characters max per file read. Same pattern — truncate + notice.

---

### 3. `src/orchestrator/benchmark.py` — Add inter-config sleep

In the `run_suite()` method, after each call to `_run_single_config()`, add `time.sleep(60)` to allow the OpenAI TPM bucket to partially refill between configs. This prevents cascading 429s from consecutive heavy configs.

Import `time` at the top if not already imported.

The sleep should only apply in non-dry-run mode (skip it for `self.dry_run == True`).

In the single-run branch (the `else:` block with `for config in configs:`), after `_run_single_config(...)` and before the next iteration, insert:

```python
if not self.dry_run:
    time.sleep(60)
```

Also add the same sleep in the multi-run loop (the `for rep in range(1, self.n_runs + 1):` block), after each `_run_single_config(...)` call.

---

### 4. `src/orchestrator/benchmark.py` and `src/features/agent_integration/agno_runner.py` — Token hard stop

**In `benchmark.py`**: Change the per-config token limit from a WARNING to a hard abort. In `_run_single_config`, after `runner.run(...)` returns `run_metrics`, check:

```python
if run_metrics.total_tokens > 150_000:
    self.logger.warning("Config %s used %d tokens (limit 150k) — marking as over-budget", 
                        config.id, run_metrics.total_tokens)
    # Still save results, but flag it
    run_metrics = run_metrics.model_copy(update={"token_exceeded": True})
```

Actually `token_exceeded` is already set via `cost_guard.record()`. The real issue is the token check happens AFTER the run. To make it a pre-emptive limit, pass `max_tokens_per_config=150_000` to `AgnoRunner`.

**In `agno_runner.py`**: Add a `max_input_tokens: int = 150_000` parameter to `AgnoRunner.__init__`. In `_build_agent()`, pass `max_tokens=4096` (already done for output). 

More importantly, in the `run()` method, after the agent finishes, check if `metrics_data.get("input_tokens", 0) > self.max_input_tokens` and log a warning.

Actually the REAL enforcement is via `tool_call_limit` (item 1) and output truncation (item 2). The `max_input_tokens` check is a post-hoc audit. Keep it as a warning for now but ensure it's logged clearly.

**Simpler approach for item 4**: In `BenchmarkOrchestrator.__init__`, change the `CostGuard` initialization to use stricter limits:

Find the line:
```python
self.cost_guard = CostGuard(
    max_suite_usd=_kwargs.get("max_suite_usd", 5.0),
    max_config_usd=_kwargs.get("max_config_usd", 0.15),
    max_tokens_per_config=_kwargs.get("max_tokens_per_config", 500_000),
```

Change the defaults to:
```python
self.cost_guard = CostGuard(
    max_suite_usd=_kwargs.get("max_suite_usd", 5.0),
    max_config_usd=_kwargs.get("max_config_usd", 0.15),
    max_tokens_per_config=_kwargs.get("max_tokens_per_config", 150_000),
```

This changes the default token warning threshold from 500k to 150k per config.

---

### 9. `src/orchestrator/benchmark.py` — Lower suite and config budget defaults

In `BenchmarkOrchestrator.__init__`, update `CostGuard` defaults:

```python
self.cost_guard = CostGuard(
    max_suite_usd=_kwargs.get("max_suite_usd", 2.0),      # was 5.0
    max_config_usd=_kwargs.get("max_config_usd", 0.10),   # was 0.15
    max_tokens_per_config=_kwargs.get("max_tokens_per_config", 150_000),  # was 500000
```

This makes the CostGuard abort the suite at $2.00 instead of $5.00, and warn/abort per-config at $0.10 instead of $0.15.

---

## Summary of files to change

1. `configs/provider.yaml` — `max_steps: 50` → `max_steps: 15`
2. `src/features/tool_registry/basic_tools.py` — truncate `read_all` to 50k chars, `read` to 20k chars
3. `src/orchestrator/benchmark.py` — sleep(60) between configs (non-dry-run only), lower CostGuard defaults (suite $2, config $0.10, tokens 150k)
4. `src/features/agent_integration/agno_runner.py` — (no change needed if items 1+2+3 are done; tool_call_limit=15 is now enforced by provider.yaml)

---

## Validation

After changes, run a quick sanity check:
```bash
wsl -e bash -lc "bash /mnt/c/Users/User/a_projects/tools_token_economy/scripts/run_wsl.sh --dry-run --config-ids 01_cursor_like 03_gemini_like"
```

Then run the full real benchmark:
```bash
bash /mnt/c/Users/User/a_projects/tools_token_economy/scripts/run_wsl.sh
```

Expected: all 20 configs complete, total cost < $2.00, no 429 errors (or rare, self-resolving).
