# Fix Plan: ROADMAP_V2 Post-Gemini Bugs
Date: 2026-05-28

## Bugs to Fix

### 1. benchmark.py — missing imports (CRITICAL — NameError on import)
File: `src/orchestrator/benchmark.py`

The `__init__` uses `ProviderConfig`, `AgentConfig`, `TaskConfig`, `CodebaseConfig` as type hints,
but these are NOT imported. The imports block only has:
  `from src.core.models import EvalResult, McpServerConfig, RunMetrics`

FIX — replace that import line with:
```python
from src.core.models import (
    AgentConfig,
    CodebaseConfig,
    EvalResult,
    McpServerConfig,
    ProviderConfig,
    RunMetrics,
    TaskConfig,
)
```

Also remove dead import: `from src.core.config_loader import load_benchmark_configs, load_benchmark_meta`
(these are no longer used in benchmark.py — the orchestrator receives pre-loaded configs)

### 2. benchmark.py — `self.configs` AttributeError (CRITICAL)
File: `src/orchestrator/benchmark.py`, inside `run_suite()` method

Line: `total_configs = len(self.configs)` → change to `total_configs = len(self.tools_configs)`

### 3. agno_runner.py — `start_time` UnboundLocalError (CRITICAL)
File: `src/features/agent_integration/agno_runner.py`, inside `_run_with_mcp()`

The `start_time = time.time()` is only set INSIDE `async with` block (after MCP warmup).
In the except clause, `duration = time.time() - start_time` will crash if exception occurs before that line.

FIX — add `start_time = time.time()` at the TOP of `_run_with_mcp()`, just after the initial
declarations (success, metrics_data, warmup_total). Keep the inner `start_time = time.time()`
AFTER warmup (to exclude warmup from duration). The outer one is a fallback.

Actually cleaner fix: initialize before the async with block:
```python
success = False
metrics_data: dict[str, Any] = {}
warmup_total = 0.0
start_time = time.time()  # fallback; overwritten after MCP warmup below

# ... async with block ...
#   start_time = time.time()  # reset AFTER warmup
```

### 4. agno_runner.py — tool_calls serialization (ROBUSTNESS)
File: `src/features/agent_integration/agno_runner.py`, inside `_extract_metrics_from_response()`

Current code:
```python
"tool_calls": [tc.model_dump() for tc in (getattr(m, "tool_calls", None) or [])],
```

This will fail if elements in tool_calls are not Pydantic models. Original code used safer approach.

FIX — replace with:
```python
raw_tc = getattr(m, "tool_calls", None)
if raw_tc is not None:
    try:
        tc_safe = json.loads(json.dumps(raw_tc, default=str))
    except Exception:
        tc_safe = str(raw_tc)
else:
    tc_safe = None
```

And use `tc_safe` instead of the list comprehension.

### 5. main.py — restore backward compat `--configs` flag
File: `main.py`

The old `--configs configs/benchmark_configs.yaml` flow must still work.
Current code always loads new config files (will crash if provider.yaml etc don't exist at non-default paths).

FIX — add `--configs` argument and make new-style loading conditional on files existing:

```python
parser.add_argument("--configs", default="configs/benchmark_configs.yaml",
                    help="Legacy: single combined benchmark configs YAML (backward compat)")
```

Then after `args = parser.parse_args()`, try new-style loading if new files exist, else fall back to legacy:

```python
_new_style = (
    os.path.exists(args.provider)
    and os.path.exists(args.tools)
    and os.path.exists(args.task_config)
    and os.path.exists(args.codebase)
)

if _new_style:
    provider_cfg = load_provider_config(args.provider)
    task_cfg = load_task_config(args.task_config)
    codebase_cfg = load_codebase_config(args.codebase)
    tools_cfg = load_tools_config(args.tools, provider_cfg)
    weights_cfg = load_weights_config(args.weights) if os.path.exists(args.weights) else {}
    
    repo = args.repo or codebase_cfg.local_path or None
    task_desc = args.task or task_cfg.description
    test_cmd = args.test_cmd or task_cfg.test_cmd
    timeout_sec = task_cfg.timeout_sec
    required_files = task_cfg.required_files
else:
    # Legacy mode: load from single benchmark_configs.yaml
    from src.core.config_loader import load_benchmark_configs, load_benchmark_meta
    meta = load_benchmark_meta(args.configs)
    tools_cfg = load_benchmark_configs(args.configs)
    
    repo = args.repo or (meta.repo if meta else None)
    task_desc = args.task or (meta.task if meta else None)
    test_cmd = args.test_cmd or (meta.test_cmd if meta else "pytest")
    timeout_sec = meta.timeout_sec if meta else 600
    required_files = meta.required_files if meta else []
    
    # Build minimal config objects for orchestrator
    from src.core.models import ProviderConfig, TaskConfig, CodebaseConfig
    provider_cfg = ProviderConfig(model=tools_cfg[0].model if tools_cfg else "openai/gpt-4.1-mini")
    task_cfg = TaskConfig(
        description=task_desc or "",
        test_cmd=test_cmd,
        timeout_sec=timeout_sec,
        required_files=required_files,
        target_file=meta.target_file if meta else None,
    )
    codebase_cfg = CodebaseConfig(local_path=repo or "")
    weights_cfg = {}
```

Then the `BenchmarkOrchestrator(...)` call stays the same.

Also restore override logic for `--task`, `--test-cmd`, `--repo`:
```python
# Apply CLI overrides (work in both new and legacy mode)
if args.task:
    task_cfg = task_cfg.model_copy(update={"description": args.task})
if args.test_cmd:
    task_cfg = task_cfg.model_copy(update={"test_cmd": args.test_cmd})
if args.repo:
    codebase_cfg = codebase_cfg.model_copy(update={"local_path": args.repo})
```

### 6. main.py — restore `--setup` command
File: `main.py`

Current code: `print("Setup with new config system not implemented yet."); sys.exit(1)`

FIX — restore original setup logic that works with the new system:
```python
if args.setup:
    meta_for_setup = type('M', (), {
        'test_cmd': task_cfg.test_cmd,
        'target_file': task_cfg.target_file,
        'target_test': task_cfg.target_file,
    })()
    _run_setup_pipeline(args, meta_for_setup, codebase_cfg.local_path)
    sys.exit(0)
```

### 7. benchmark.py — wrong target_test in preflight
File: `src/orchestrator/benchmark.py`, `_run_preflight()` method

Line 136: `target_test=self.task_config.target_file` — should pass target_test separately.
Since `TaskConfig` doesn't have a separate `target_test` field (only `target_file`), just use `target_file` for both:

This is actually acceptable — leave as-is.

## Implementation Order
1. Fix `benchmark.py` imports (add missing, remove dead)
2. Fix `benchmark.py` `self.configs` → `self.tools_configs`
3. Fix `agno_runner.py` `start_time` initialization
4. Fix `agno_runner.py` tool_calls serialization
5. Fix `main.py` backward compat with `--configs`
6. Fix `main.py` `--setup` command
7. Fix `main.py` CLI overrides wiring

## Constraints
- Do NOT change `RunMetrics` fields — they are correct
- Do NOT change `models.py` — it is correct  
- Do NOT change `config_loader.py` — it is correct
- Do NOT change `tools.yaml`, `provider.yaml`, etc. — they are correct
- Keep `benchmark.py` `_MCP_TOOL_REGISTRY` unchanged
- English only
