# Plan: Cost & Reliability Fixes for Token Economy Benchmark
**Date:** 2026-05-29
**Priority:** P0 → P1 → P2 (implement in this order)
**Do NOT implement:** P1.1 (merge 7 judges into 1), keep read_all but add soft cap (P2.3)

---

## Files to modify

| File | Changes |
|------|---------|
| `src/features/agent_integration/agno_runner.py` | P0.1, P0.2, P0.3, P0.4, P1.2, P1.3, P1.6, P1.8 |
| `src/core/models.py` | P0.2, P0.5, P1.9, P1.10, P2.7 |
| `src/orchestrator/benchmark.py` | P1.4, P1.5 |
| `src/features/tool_registry/basic_tools.py` | P1.2 (read cap), P2.3 (read_all soft cap) |
| `configs/provider.yaml` | P1.7, P2.7 |

---

## P0 — Critical fixes (implement ALL first)

### P0.1 — Move `worktree_path` OUT of system prompt
**File:** `src/features/agent_integration/agno_runner.py`
**Method:** `_build_agent()`

**Problem:** The first instruction is:
```python
f"You are a coding agent working in the repository at: {worktree_path}"
```
`worktree_path` contains a unique timestamp (e.g. `worktrees/run_20260529_132538_03_gemini_like`).
OpenAI prompt caching requires an **exact prefix match**. Since this string is unique per run,
the cache key never matches between runs — we pay full input price every time (no 75% discount).

**Fix:** Make the system prompt 100% static. Inject `worktree_path` into the **user message** prefix instead.

In `_build_agent()`, remove the dynamic `worktree_path` from `instructions`. Instructions should be:
```
"You are a coding agent. Complete the task using only the tools provided.",
"Always use RELATIVE file paths (relative to the repository root) when calling file tools. Never use absolute paths.",
"MANDATORY: You MUST call at least one file-modification tool (write, edit, patch, or insert_after) to save your code changes to disk before saying TASK_COMPLETE. Reading files and thinking about changes is not enough - you must persist changes with a tool call.",
"Workflow: (1) Use retrieval tools to understand the codebase. (2) Save your changes using edit (modify specific section - preferred for existing files), write (full file replacement - only when creating new files or replacing entirely), patch (unified diff), or insert_after (add new code after anchor). (3) Verify by reading the file back. (4) Output exactly: TASK_COMPLETE",
"If a tool returns an error, try a different approach - do not repeat the exact same tool call.",
"Never output TASK_COMPLETE if you have not called at least one of: write, edit, patch, insert_after.",
"CRITICAL: NEVER delete, truncate, or overwrite existing code. When adding to an existing file, preserve ALL existing content.",
"CRITICAL: NEVER remove or replace existing tests. The test file already contains tests. You must ADD a new test without touching any existing test.",
"Read files in LARGE blocks (at least 100-200 lines per read call). Do NOT read the same file in small chunks of 20-30 lines.",
"Efficiency: Use the shell tool's multi_cmd parameter to run multiple related commands in a single turn.",
```

In `_run_with_mcp()` and `run()`, before calling `runner.run()` / `agent.arun()`, prepend a repo context line to the **task description**:
```python
repo_context = f"[Repository path: {worktree_path}]\n\n"
full_task = repo_context + full_task
```
This context will be in the user message, not system prompt, so it does NOT break caching.

### P0.2 — Track cache_read_tokens, fix cost_usd calculation
**Files:** `src/features/agent_integration/agno_runner.py`, `src/core/models.py`

**Part A — RunMetrics fields (models.py):**
Add these fields to `RunMetrics`:
```python
cache_read_tokens: int = 0
cache_write_tokens: int = 0
```

**Part B — Collect from agno (agno_runner.py, in `_extract_metrics_from_response`):**
After reading `response.metrics.input_tokens`, also read:
```python
metrics_data["cache_read_tokens"] = getattr(response.metrics, "cache_read_tokens", 0) or 0
metrics_data["cache_write_tokens"] = getattr(response.metrics, "cache_write_tokens", 0) or 0
```

**Part C — Fix cost_usd computation (models.py, in `cost_usd` computed_field):**

Current formula (WRONG - double counts tool_tokens):
```python
input_cost = (self.input_tokens / 1_000_000) * p["input"]
output_cost = (self.output_tokens / 1_000_000) * p["output"]
tool_cost = (self.tool_tokens / 1_000_000) * p["input"]   # BUG: tool_tokens are already in input_tokens
```

New formula (correct):
```python
# cache_read_tokens get 75% discount (OpenAI automatic caching)
cached_input = self.cache_read_tokens
non_cached_input = max(0, self.input_tokens - cached_input)
input_cost = (non_cached_input / 1_000_000) * p["input"]
cached_cost = (cached_input / 1_000_000) * p.get("cached_input", p["input"] * 0.25)
output_cost = (self.output_tokens / 1_000_000) * p["output"]
# Do NOT add tool_tokens separately - they are already counted inside input_tokens
return input_cost + cached_cost + output_cost
```

Also add `cached_input` price field to the pricing dict for gpt-4.1-mini:
```python
"gpt-4.1-mini": {"input": 0.40, "output": 1.60, "cached_input": 0.10},
"openai/gpt-4.1-mini": {"input": 0.40, "output": 1.60, "cached_input": 0.10},
"gpt-4.1-nano": {"input": 0.10, "output": 0.40, "cached_input": 0.025},
"openai/gpt-4.1-nano": {"input": 0.10, "output": 0.40, "cached_input": 0.025},
"gpt-4o-mini": {"input": 0.15, "output": 0.60, "cached_input": 0.075},
"openai/gpt-4o-mini": {"input": 0.15, "output": 0.60, "cached_input": 0.075},
```

### P0.3 — Runtime cost-cutoff via pre_hook
**File:** `src/features/agent_integration/agno_runner.py`

**Problem:** CostGuard only checks between configs, not during `agent.run()`. A runaway run can spend $2.25 unchecked.

**Solution:** Use agno's `pre_hooks` mechanism to inject a budget check before each LLM call.
Pre-hooks receive the agent messages context before each LLM invocation — we can estimate tokens and abort.

Add a new method `_build_budget_pre_hook(self)` that returns a callable.
The hook maintains a shared mutable accumulator. Before each LLM call, it estimates current cumulative
cost from the messages passed to it and raises `BudgetExceededError` if over limit.

```python
def _build_budget_pre_hook(self, max_cost_usd: float = 0.50):
    """Returns a pre_hook that raises BudgetExceededError if estimated cost exceeds max_cost_usd."""
    state = {"estimated_cost": 0.0}
    pricing = {
        "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
        "openai/gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    }
    model_id = self._extract_model_id()
    p = pricing.get(self.config.model, pricing.get("openai/gpt-4.1-mini"))

    def budget_hook(agent_instance):
        # Estimate input tokens from all messages in current context
        messages = getattr(agent_instance, 'memory', None)
        if messages is None:
            return
        # Get the messages list from agent memory
        msg_list = []
        if hasattr(messages, 'messages'):
            msg_list = messages.messages or []
        elif isinstance(messages, list):
            msg_list = messages
        
        total_chars = sum(len(str(getattr(m, 'content', '') or '')) for m in msg_list)
        estimated_tokens = total_chars // 4
        estimated_cost = (estimated_tokens / 1_000_000) * p["input"]
        state["estimated_cost"] = estimated_cost
        
        if estimated_cost > max_cost_usd:
            raise BudgetExceededError(
                f"Pre-hook aborted: estimated input cost ${estimated_cost:.4f} "
                f"exceeds per-config limit ${max_cost_usd:.2f}"
            )
    
    return budget_hook
```

In `_build_agent()`, pass the pre_hook to the Agent:
```python
budget_hook = self._build_budget_pre_hook(max_cost_usd=0.50)
return Agent(
    model=OpenAIChat(id=model_id, max_tokens=4096),
    tools=tools,
    instructions=...,
    markdown=False,
    tool_call_limit=effective_limit,
    pre_hooks=[budget_hook],
)
```

In the `run()` and `_run_with_mcp()` exception handlers, catch `BudgetExceededError` from `agno.agent` or `src.features.cost_guard`:
```python
except BudgetExceededError:
    _log.warning("Budget pre-hook aborted agent run at step N")
    success = False
    metrics_data["execution_result"] = "budget_exceeded"
```

**Important:** The `max_cost_usd` for the hook should default to `0.50` and should be configurable via `AgnoRunner.__init__` parameter `max_config_cost_usd: float = 0.50`.

### P0.4 — Sanity guard for phantom tokens
**File:** `src/features/agent_integration/agno_runner.py`, in `_extract_metrics_from_response()`

After collecting `metrics_data["input_tokens"]`, add:
```python
# Sanity check: if we have huge input tokens but zero message trace, something went wrong
if (metrics_data["input_tokens"] > 200_000 and 
    not any(m.get("role") == "assistant" for m in msgs)):
    _log.error(
        "PHANTOM TOKENS DETECTED: input_tokens=%d but no assistant messages in trace. "
        "Likely agno internal retry or exception during model call. "
        "Setting execution_result=telemetry_corrupt.",
        metrics_data["input_tokens"]
    )
    metrics_data["execution_result"] = "telemetry_corrupt"
    # Zero out the phantom tokens so cost_usd is not inflated
    metrics_data["input_tokens"] = 0
    metrics_data["output_tokens"] = 0
```

---

## P1 — Structural improvements

### P1.2 — Fix FileReadTool chunk size (CRITICAL)
**File:** `src/features/tool_registry/basic_tools.py`

**Problem:** `_MAX_CHARS = 2_500` in `FileReadTool.execute()` limits reads to ~60 lines.
Agents are forced to chunk one file into 5-6 separate reads, each adding to cumulative context cost.

**Fix:** Increase `_MAX_CHARS` from `2_500` to `20_000` (≈ 5000 tokens, reasonable for a single file section):
```python
_MAX_CHARS = 20_000
```
Update the truncation message accordingly:
```
f"\n\n[OUTPUT TRUNCATED at {_MAX_CHARS} chars. Use start_line/end_line to read a specific section.]"
```

Also update the default for `end_line` behavior: when `end_line == -1`, don't artificially limit lines.
The current code is fine; just increase the char cap.

### P2.3 — read_all soft cap (NOT a hard removal)
**File:** `src/features/tool_registry/basic_tools.py`

**Current:** `ReadAllTool._MAX_CHARS = 8_000`

**Problem reported:** read_all can trigger runaway reads when called repeatedly.
**User instruction:** Add a soft cap, not too strict.

**Fix:** Increase `_MAX_CHARS` in `ReadAllTool` from `8_000` to `30_000` but add a **file count cap**
and a per-file size limit. This lets it cover more of a real repo without going infinite:

```python
_MAX_CHARS = 30_000
_MAX_FILES = 30  # read at most 30 files

def execute(self) -> ToolResult:
    output = []
    files_read = 0
    for root, dirs, files in os.walk(self.worktree_path):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('venv', '__pycache__', 'node_modules', '.git')]
        for file in files:
            if files_read >= _MAX_FILES:
                output.append(f"\n[TRUNCATED: read_all limit of {_MAX_FILES} files reached. Use rg/read for remaining files.]")
                break
            _, ext = os.path.splitext(file)
            if ext.lower() in _BINARY_EXTENSIONS:
                continue
            rel_path = os.path.relpath(os.path.join(root, file), self.worktree_path)
            try:
                with open(os.path.join(root, file), encoding="utf-8") as f:
                    content = f.read(5_000)  # per-file cap: 5000 chars
                output.append(f"--- FILE: {rel_path} ---\n{content}")
                files_read += 1
            except Exception:
                continue
        else:
            continue
        break  # break outer loop if inner broke

    result = "\n\n".join(output)
    if len(result) > _MAX_CHARS:
        result = result[:_MAX_CHARS] + f"\n\n[OUTPUT TRUNCATED: read_all exceeded {_MAX_CHARS} chars]"
    return self.format_result(result)
```

### P1.3 — Agno pre_hook for cumulative budget
Already covered in P0.3 above. The budget_hook is the implementation.
Make the hook's limit configurable via `AgnoRunner.__init__(max_config_cost_usd=0.50)`.

### P1.4 — Unify max_iterations / max_steps
**Files:** `src/features/agent_integration/agno_runner.py`, `src/core/models.py`

**Problem:** `tool_call_limit=min(config.max_steps, max_iterations)` limits tool calls, not LLM calls.
A model can make many LLM calls without tool calls (just "thinking").

**Fix in `_build_agent()`:** Set `tool_call_limit` to a lower value AND add a note in the config:
```python
# tool_call_limit controls tool calls. Actual model_calls may exceed this by 20%.
effective_limit = min(self.config.max_steps, self.max_iterations)
```
Also add `max_iterations: int = 20` to `ProviderConfig` (models.py) as a unified field,
and document that `max_steps` in `AgentConfig` overrides it per-config.

In `configs/provider.yaml`, change `max_steps: 50` to `max_steps: 20` (lower default for medium task).

### P1.5 — Remove hardcoded sleep(60) between configs
**File:** `src/orchestrator/benchmark.py`

**Problem:** `time.sleep(60)` between every config = 20 minutes wasted per full suite run.

**Fix:** The `RateLimiter` at 10 RPM already handles rate limiting when active.
Remove the `time.sleep(60)` calls from all three locations:
- `benchmark.py:399-400` (multi-run path)
- `benchmark.py:425-426` (single-run path)
- `benchmark.py:508-509` (retry path)

Replace with a much shorter adaptive sleep:
```python
# Small buffer to avoid hammering the API between configs
time.sleep(5)
```
Or remove entirely and rely on RateLimiter. Since RateLimiter is now active in both paths (after P1.6), removing sleep is safe.

If you want to be conservative, replace `sleep(60)` with `sleep(10)`.

### P1.6 — Apply RateLimiter in _run_with_mcp
**File:** `src/features/agent_integration/agno_runner.py`

**Problem:** `self._rate_limiter` is used in sync path (line ~461) but NOT in `_run_with_mcp()`.

**Fix:** Wrap the `agent.arun()` call in `_run_with_mcp()` with rate limiter:
```python
# Before: response = await asyncio.wait_for(agent.arun(task_description), timeout=...)
# After:
with self._rate_limiter:
    response = await asyncio.wait_for(
        agent.arun(task_description),
        timeout=float(self.timeout_sec),
    )
```
Note: `self._rate_limiter` is a `RateLimiter` context manager. Verify it is thread-safe for async usage.
If not, convert to asyncio.Semaphore or apply rate limiting just before the async call.

### P1.7 — Lower max_steps default
**File:** `configs/provider.yaml`

Change:
```yaml
max_steps: 50
```
To:
```yaml
max_steps: 20
```

This reduces the max tool_call_limit ceiling from 50 to 20 for medium tasks.

### P1.8 — Move build_tool_restriction_prefix into system instructions
**Files:** `src/orchestrator/benchmark.py`, `src/features/agent_integration/agno_runner.py`

**Problem:** Tool restriction prefix is prepended to `task_description` (user message).
This means the prefix (which lists tool names) changes per-config, breaking cache across configs.

**Fix:** Pass the prefix as additional system instructions to `AgnoRunner`, not as part of task.

In `benchmark.py`, change:
```python
# Current:
prefix = build_tool_restriction_prefix(config)
full_task = (prefix + task_description) if prefix else task_description
run_metrics = runner.run(full_task, ...)

# New:
prefix = build_tool_restriction_prefix(config)
run_metrics = runner.run(
    task_description,  # clean task
    worktree_path=worktree_path,
    test_cmd=self.test_cmd,
    log_path=log_path,
    system_prefix=prefix,  # new parameter
)
```

In `agno_runner.py`, add `system_prefix: str = ""` parameter to `run()`.
In `_build_agent()`, add `system_prefix` as a parameter and prepend to `instructions`:
```python
all_instructions = []
if system_prefix:
    all_instructions.append(system_prefix)
all_instructions.extend([...static instructions...])
```

### P1.9 — Fix pricing dict (add cached_input, fix fallback)
**File:** `src/core/models.py`

Already covered in P0.2. In addition:

**Fix unknown model fallback (P1.10):**
Replace silent gemini fallback with a warning:
```python
model_key = self.model_name
p = pricing.get(model_key)
if p is None:
    # Try stripping openai/ prefix
    stripped = model_key.replace("openai/", "").replace("google/", "").replace("anthropic/", "")
    p = pricing.get(stripped)
if p is None:
    _log.warning(  # Use logging - note: this is a property, use print or set a class-level warning flag
        "Unknown model pricing for '%s', defaulting to gpt-4.1-mini rates. "
        "Add pricing entry to RunMetrics.cost_usd to fix this.",
        model_key
    )
    p = pricing["openai/gpt-4.1-mini"]  # fail-safe to the actual model being used, not gemini
```

Note: since `cost_usd` is a Pydantic `@computed_field`, you cannot use `logging` directly (no logger in scope).
Use a simple `import warnings; warnings.warn(...)` instead, or just set `p = pricing["openai/gpt-4.1-mini"]` silently.

### P2.4 — Add "read large blocks" instruction
Already done in P0.1 where we added to the static instructions:
```
"Read files in LARGE blocks (at least 100-200 lines per read call). Do NOT read the same file in small chunks of 20-30 lines.",
```

### P2.6 — Add commit SHA tracking
**File:** `src/orchestrator/benchmark.py`, in `_capture_baseline()`

After `self._setup_target_repo()`, capture the current commit SHA and log it:
```python
try:
    sha_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path, capture_output=True, text=True, timeout=10
    )
    if sha_result.returncode == 0:
        sha = sha_result.stdout.strip()
        self.logger.info("Target repo commit: %s", sha)
        # Optionally save to run metadata
except Exception:
    pass
```
This is informational only - does not block execution.

### P2.7 — Add seed to ProviderConfig and OpenAIChat
**File:** `src/core/models.py` and `src/features/agent_integration/agno_runner.py`

In `ProviderConfig` (models.py), add:
```python
seed: int | None = 42
```

In `configs/provider.yaml`, add:
```yaml
seed: 42
```

In `agno_runner.py`, in `_build_agent()`, pass seed:
```python
OpenAIChat(id=model_id, max_tokens=4096, seed=self.config_seed)
```
Add `config_seed` as a field derived from `ProviderConfig.seed` passed through `BenchmarkOrchestrator` → `AgnoRunner.__init__`.

Actually, simpler: add `seed: int | None = None` to `AgnoRunner.__init__()` and pass it to `OpenAIChat`:
```python
OpenAIChat(id=model_id, max_tokens=4096, seed=self.seed if self.seed is not None else 42)
```

In `BenchmarkOrchestrator._run_single_config()`, pass `seed=self.provider_config.seed` to `AgnoRunner`.

### P2.8 — Secure GIT_DIR in make_wrapper (tool execution)
**File:** `src/features/agent_integration/agno_runner.py`, in `make_wrapper()`

The tool wrapper calls `_tool.execute()`. For shell-based tools, ensure `GIT_DIR` is not inherited from parent.
This is handled inside `ShellExecutor` — verify that `ShellExecutor` sets `cwd=worktree_path` and
doesn't inherit `GIT_DIR` env var. Add a note/comment if already handled.

If `ShellExecutor` does not strip `GIT_DIR`, modify it (in `src/features/isolation.py` or wherever `ShellExecutor` is defined) to explicitly unset `GIT_DIR`:
```python
env = os.environ.copy()
env.pop("GIT_DIR", None)
env.pop("GIT_WORK_TREE", None)
subprocess.run(cmd, cwd=self.worktree_path, env=env, ...)
```

---

## Summary of changes by file

### `src/features/agent_integration/agno_runner.py`
1. (P0.1) Make `instructions` list fully static — remove `worktree_path` from first item
2. (P0.1) Add "read files in large blocks" instruction
3. (P0.1) Add `worktree_path` as a prefix in user message (in both `run()` and `_run_with_mcp()`)
4. (P0.2) Read `cache_read_tokens`, `cache_write_tokens` from `response.metrics`
5. (P0.3) Add `_build_budget_pre_hook()` method; pass to `Agent(pre_hooks=[...])`
6. (P0.3) Catch `BudgetExceededError` in run()/`_run_with_mcp()` exception handlers
7. (P0.4) Add phantom-tokens sanity check in `_extract_metrics_from_response()`
8. (P1.6) Apply `self._rate_limiter` in `_run_with_mcp()` before `agent.arun()`
9. (P1.7) Already via provider.yaml config change
10. (P1.8) Accept `system_prefix` parameter in `run()`, pass to `_build_agent()`
11. (P2.7) Accept `seed` parameter in `__init__`, pass to `OpenAIChat`
12. (P2.8) Note/fix GIT_DIR isolation in tool execution

### `src/core/models.py`
1. (P0.2) Add `cache_read_tokens: int = 0` and `cache_write_tokens: int = 0` to `RunMetrics`
2. (P0.5) Remove `tool_cost` from `cost_usd` formula
3. (P0.2/P1.9) Add `cached_input` to pricing dict for all OpenAI models
4. (P1.10) Fix unknown model fallback (warn + use gpt-4.1-mini, not gemini)
5. (P2.7) Add `seed: int | None = 42` to `ProviderConfig`

### `src/orchestrator/benchmark.py`
1. (P1.5) Replace `time.sleep(60)` with `time.sleep(5)` in all 3 locations
2. (P1.8) Pass `system_prefix` to `runner.run()` instead of prepending to task
3. (P2.6) Log commit SHA after `_setup_target_repo()`
4. (P2.7) Pass `seed=self.provider_config.seed` to `AgnoRunner`

### `src/features/tool_registry/basic_tools.py`
1. (P1.2) `FileReadTool._MAX_CHARS`: change `2_500` → `20_000`
2. (P2.3) `ReadAllTool`: add `_MAX_FILES = 30` limit, per-file cap of 5000 chars, increase `_MAX_CHARS` from `8_000` to `30_000`

### `configs/provider.yaml`
1. (P1.7) `max_steps: 50` → `max_steps: 20`
2. (P2.7) Add `seed: 42`

---

## Testing after implementation

Run the following to verify:
```bash
# 1. Dry run — verifies no import errors
wsl bash -c "cd /mnt/c/Users/User/a_projects/tools_token_economy && uv run python main.py --dry-run --config-ids 01_cursor_like"

# 2. Quick real run on 2 cheap configs to check caching and cost
wsl bash -c "cd /mnt/c/Users/User/a_projects/tools_token_economy && uv run python main.py --config-ids 04_codex_like,09_rg"

# 3. Check that cache_read_tokens > 0 in metrics.json (only appears after 2nd call)
# After running same config twice, verify: cat results/run_*/metrics.json | python -c "import sys,json; d=json.load(sys.stdin); print('cache_read:', d.get('cache_read_tokens'))"

# 4. Unit tests
wsl bash -c "cd /mnt/c/Users/User/a_projects/tools_token_economy && uv run pytest tests/ -q"
```

Expected results:
- `cost_usd` in metrics.json should be lower (no double tool_cost)
- `cache_read_tokens` field appears in metrics.json
- No phantom tokens: if a run has `model_calls=0` then `input_tokens=0`
- Runs finish faster (no sleep(60) delays)
- FileReadTool no longer chunks files into 20-line slices

---

## IMPORTANT NOTES for Gemini

1. Do NOT implement P1.1 (merge 7 LLM judges). The LLMJudge class stays as-is.
2. For P0.3 (pre_hook): agno's `pre_hooks` parameter accepts a list of callables that receive the Agent instance. Check the actual agno API signature for pre_hooks before implementing — it may be `def hook(agent: Agent) -> None` or `def hook(messages: list) -> None`. Use the correct signature from agno source/docs.
3. For P1.6 (rate_limiter in async): if `RateLimiter` uses threading.Lock internally, it may deadlock in asyncio context. Wrap it in `asyncio.to_thread(lambda: rate_limiter.__enter__())` or use `loop.run_in_executor`. Check `src/features/rate_limiter.py` first.
4. The `BudgetExceededError` import in agno_runner.py already exists: `from src.features.cost_guard import BudgetExceededError, CostGuard`
5. Keep all existing tests passing. Run `uv run pytest tests/ -q` after each file modification.
6. Do not remove or rename `BenchmarkMeta` from models.py — it may be used in tests.
