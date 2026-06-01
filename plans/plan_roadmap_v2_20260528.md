# Plan: ROADMAP_V2 Implementation
Date: 2026-05-28

## Goal
Implement all phases from ROADMAP_V2.md in order: config refactoring → new RunMetrics fields → MCP warmup → dashboard columns → Streamlit MVP.

## Current State Observations
- `agent_messages.json` and `final.patch` are ALREADY saved in `agno_runner.py::_validate_run()` and `_extract_metrics_from_response()` — Phase 1a artifacts are done.
- `benchmark_weights.yaml` already exists at `configs/benchmark_weights.yaml`.
- CLI already has `--task` (string override) and `--configs` (YAML path).
- `BenchmarkOrchestrator.__init__` accepts `test_cmd` via kwargs.
- The `configs/benchmark_configs.yaml` id field is e.g. `"01_cursor_like"` (underscore format). The new `tools.yaml` should use numeric id like `"01"` with separate `name`.

---

## Phase 0: Config Refactoring

### Files to CREATE

#### `configs/provider.yaml`
```yaml
provider: openai
model: openai/gpt-4.1-mini
api_base: ""
max_steps: 50
temperature: 0.0
```

#### `configs/tools.yaml`
Take all 20 configs from `benchmark_configs.yaml`, strip `model` and `max_steps` fields (they come from provider.yaml), keep `id`, `name`, `archetype`, `tools`. The id format should be short e.g. `"01"` matching the numeric prefix.

```yaml
configs:
  - id: "01_cursor_like"
    name: "Cursor-like"
    archetype: "cursor"
    tools: ["repo_map", "simple_rag", "read", "write", "patch", "insert_after", "shell"]
  # ... all 20 configs, no model/max_steps
```
IMPORTANT: Keep the id format as-is (e.g. "01_cursor_like") for backward compat with results/ directory naming.

#### `configs/tasks/medium.yaml`
```yaml
difficulty: medium
name: "Execution Timeout - Jira Sync Jobs"
description: |
  Implement a system-wide execution timeout for all background data processing
  operations (specifically Jira synchronization and metrics recalculation jobs).

  1. Identify the primary service responsible for dispatching these jobs
     to the external orchestrator.
  2. Modify this service to enforce a mandatory 1-hour (3600 seconds)
     timeout. This timeout must be passed as a 'timeout' tag within
     the execution parameters sent to the orchestrator.
  3. Locate all call sites (API endpoints and internal handlers) that
     initiate these background jobs and update them to comply with the
     new signature/logic.
  4. Ensure that all unit tests related to job triggering are updated
     to reflect this change and continue to pass.

  You MUST use your retrieval tools to discover the relevant components.
  Finalize by calling write/patch to save changes and output: TASK_COMPLETE.
test_cmd: "uv run --extra dev pytest tests/unit/ -q"
timeout_sec: 1200
target_file: "tests/unit/test_api_google_oauth.py"
required_files:
  - "tests/unit/test_api_google_oauth.py"
  - "src/api/google_oauth.py"
success_criteria:
  - "All new tests pass"
```

#### `configs/tasks/easy.yaml`
```yaml
difficulty: easy
name: "Add health check endpoint"
description: |
  Add a /health endpoint to the API that returns {"status": "ok"}.
  Use your retrieval tools to find where existing endpoints are defined,
  then add the new endpoint following the same pattern.
  Finalize by calling write/patch to save changes and output: TASK_COMPLETE.
test_cmd: "uv run --extra dev pytest tests/unit/ -q"
timeout_sec: 600
target_file: "src/api/health.py"
required_files:
  - "src/api/health.py"
success_criteria:
  - "Health endpoint returns 200"
```

#### `configs/tasks/hard.yaml`
```yaml
difficulty: hard
name: "Implement full OAuth2 PKCE flow"
description: |
  Implement a complete OAuth2 PKCE (Proof Key for Code Exchange) flow for
  Google authentication. This requires:
  1. Generating and storing a code_verifier and code_challenge
  2. Modifying the authorization URL to include code_challenge and method
  3. Implementing the token exchange with code_verifier
  4. Adding comprehensive unit tests for all new code paths
  Use your retrieval tools to understand the existing OAuth implementation first.
  Finalize by calling write/patch to save changes and output: TASK_COMPLETE.
test_cmd: "uv run --extra dev pytest tests/unit/ -q"
timeout_sec: 1800
target_file: "src/api/google_oauth.py"
required_files:
  - "src/api/google_oauth.py"
  - "tests/unit/test_api_google_oauth.py"
success_criteria:
  - "PKCE flow tests pass"
```

#### `configs/codebase.yaml`
```yaml
name: process_metrics_platform_v2
github_url: "https://github.com/letya999/process_metrics_platform_v2"
branch: main
commit: HEAD
local_path: "C:\\Users\\User\\a_projects\\process_metrics_platform_v2"
install_cmd: "uv sync --extra dev"
```

### Files to MODIFY

#### `src/core/models.py`
Add three new Pydantic models AFTER the existing ones:

```python
class ProviderConfig(BaseModel):
    provider: str = "openai"
    model: str = "openai/gpt-4.1-mini"
    api_base: str = ""
    max_steps: int = 50
    temperature: float = 0.0


class TaskConfig(BaseModel):
    difficulty: str = "medium"
    name: str = ""
    description: str = ""
    test_cmd: str = "uv run --extra dev pytest tests/unit/ -q"
    timeout_sec: int = 1200
    target_file: str | None = None
    required_files: list[str] = []
    success_criteria: list[str] = []


class CodebaseConfig(BaseModel):
    name: str = ""
    github_url: str = ""
    branch: str = "main"
    commit: str = "HEAD"
    local_path: str = ""
    install_cmd: str = "uv sync --extra dev"
```

Also add new fields to `RunMetrics`:
```python
    agent_cycles: int = 0
    time_to_target: int = 0
    context_waste_ratio: float = 0.0
    warmup_sec: float = 0.0

    @computed_field
    @property
    def avg_tokens_per_tool(self) -> float:
        if self.tool_calls == 0:
            return 0.0
        return self.tool_tokens / self.tool_calls
```

Also update `McpServerConfig` dataclass to add warmup fields:
```python
    warmup_call: str | None = None
    warmup_args: dict = field(default_factory=dict)
```
Since `McpServerConfig` is a `@dataclass`, use `field(default_factory=dict)`.
IMPORTANT: Need to import `field` from `dataclasses`.

#### `src/core/config_loader.py`
Add four new load functions:

```python
def load_provider_config(file_path: str) -> ProviderConfig:
    with open(file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return ProviderConfig(**data)


def load_tools_config(file_path: str, provider: ProviderConfig) -> list[AgentConfig]:
    with open(file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    configs = []
    for item in data.get("configs", []):
        item.setdefault("model", provider.model)
        item.setdefault("max_steps", provider.max_steps)
        configs.append(AgentConfig(**item))
    return configs


def load_task_config(file_path: str) -> TaskConfig:
    with open(file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if "description" in data:
        data["description"] = data["description"].strip()
    return TaskConfig(**data)


def load_codebase_config(file_path: str) -> CodebaseConfig:
    with open(file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return CodebaseConfig(**data)
```

Also add the new imports at the top of config_loader.py:
```python
from src.core.models import AgentConfig, BenchmarkMeta, ProviderConfig, TaskConfig, CodebaseConfig
```

#### `main.py`
Add new CLI arguments in `main()`:
```python
parser.add_argument("--provider", default="configs/provider.yaml", help="Provider config YAML")
parser.add_argument("--tools", default="configs/tools.yaml", help="Tools/strategies config YAML")
parser.add_argument("--task-config", default="configs/tasks/medium.yaml", help="Task config YAML")
parser.add_argument("--codebase", default="configs/codebase.yaml", help="Codebase config YAML")
parser.add_argument("--weights", default="configs/benchmark_weights.yaml", help="Benchmark weights YAML")
```

Then in `main()`, after `args = parser.parse_args()`, add logic to load new configs IF the new-style files exist, falling back to legacy `--configs` YAML:

```python
# Try new-style config system first
_new_style = (
    os.path.exists(args.provider)
    and os.path.exists(args.tools)
    and os.path.exists(getattr(args, 'task_config', ''))
    and os.path.exists(args.codebase)
)

if _new_style:
    from src.core.config_loader import (
        load_provider_config, load_tools_config, load_task_config, load_codebase_config
    )
    provider_cfg = load_provider_config(args.provider)
    task_cfg = load_task_config(args.task_config)
    codebase_cfg = load_codebase_config(args.codebase)
    
    # Resolve repo path: local_path overrides github_url
    repo = args.repo or (codebase_cfg.local_path if codebase_cfg.local_path else None)
    task = args.task or task_cfg.description
    test_cmd = args.test_cmd or task_cfg.test_cmd
    timeout_sec = task_cfg.timeout_sec
    # Pass tools path via a special orchestrator kwarg
    configs_path_for_orchestrator = args.tools
    provider_for_orchestrator = provider_cfg
else:
    # Legacy mode
    meta = load_benchmark_meta(args.configs)
    repo = args.repo or (meta.repo if meta else None)
    task = args.task or (meta.task if meta else None)
    test_cmd = args.test_cmd or (meta.test_cmd if meta else "pytest")
    timeout_sec = meta.timeout_sec if meta else 600
    configs_path_for_orchestrator = args.configs
    provider_for_orchestrator = None
```

The orchestrator needs to know about provider (for model) when using new-style. Pass it via a new kwarg `provider_config`.

Actually - simpler approach: the new tools.yaml + provider.yaml are loaded by config_loader. The BenchmarkOrchestrator reads configs from the tools YAML. We need to:
1. Make BenchmarkOrchestrator accept an optional `provider_config` kwarg
2. When loading tools.yaml, merge model/max_steps from provider_config

Actually the simplest approach: just pass both `--configs` path for backward compat. For new-style, generate the configs internally before passing to orchestrator.

SIMPLER DESIGN:
- If `--tools` file exists: load with `load_tools_config(args.tools, provider_cfg)` 
- Pass `configs` list directly to orchestrator (add `configs` param to `__init__`)
- If `--task-config` exists: override repo/task/test_cmd from task_cfg
- If `--codebase` exists: override repo from codebase_cfg.local_path

#### `src/orchestrator/benchmark.py`
Modify `BenchmarkOrchestrator.__init__` to accept optional `configs` list:
```python
def __init__(
    self,
    repo_path: str,
    configs_path: str,
    results_dir: str,
    worktree_base: str = "worktrees",
    dry_run: bool = False,
    timeout_sec: int = 600,
    configs: list | None = None,  # NEW: pre-loaded configs override configs_path
    required_files: list[str] | None = None,  # NEW: for context_waste_ratio
    **_kwargs,
):
    ...
    self.configs = configs if configs is not None else load_benchmark_configs(configs_path)
    self.required_files = required_files or (self.meta.required_files if self.meta else [])
```

Also pass `required_files` to `AgnoRunner.__init__` so it can compute `context_waste_ratio` and `time_to_target`.

---

## Phase 1a: New RunMetrics Fields

Already analyzed above. Changes to:
- `src/core/models.py` - add fields (see Phase 0 section)
- `src/features/agent_integration/agno_runner.py` - compute new metrics

### `agno_runner.py` changes

**Add `required_files` param to `__init__`:**
```python
def __init__(
    self,
    ...
    required_files: list[str] | None = None,  # NEW
):
    ...
    self.required_files = required_files or []
```

**In `_extract_metrics_from_response()`, add after the existing tool_exec loop:**
```python
# agent_cycles: count of 'tool' role messages (each closes one think→tool cycle)
agent_cycles = sum(
    1 for m in (response.messages or [])
    if getattr(m, "role", None) == "tool"
)
metrics_data["agent_cycles"] = agent_cycles

# context_waste_ratio
_read_tool_names = {"read", "read_all", "glob", "tree_sitter", "repo_map", "simple_rag", "lsp_symbols"}
total_read_tok = 0
useful_read_tok = 0
time_to_target = 0
cycle_num = 0

for msg in (response.messages or []):
    if getattr(msg, "role", None) == "tool":
        cycle_num += 1

for tool_exec in (response.tools or []):
    if tool_exec.tool_name not in _read_tool_names:
        continue
    res_str = str(getattr(tool_exec, "result", "") or "")
    tok = self._count_tokens(res_str)
    total_read_tok += tok
    args = getattr(tool_exec, "input", {}) or {}
    file_arg = (
        args.get("path") or args.get("file_path") or
        args.get("query") or args.get("pattern") or ""
    )
    if self.required_files and any(
        req in file_arg or file_arg in req
        for req in self.required_files
    ):
        useful_read_tok += tok
        if time_to_target == 0:
            # Find cycle number for this tool call - approximate
            time_to_target = cycle_num  # will be refined below

metrics_data["context_waste_ratio"] = (
    (total_read_tok - useful_read_tok) / total_read_tok
    if total_read_tok > 0 else 0.0
)
metrics_data["time_to_target"] = time_to_target
```

NOTE: `time_to_target` approximation - the tool_exec list doesn't directly map to cycles. We need a better approach. Since response.tools is ordered, and response.messages has role="tool" messages interleaved, we can pair them:

Actually, the simplest approach: iterate response.messages in order, tracking cycle number. When we see a "tool" message with content matching a required_file, record the cycle number.

```python
# time_to_target: cycle when first required file was read
time_to_target = 0
cycle_count = 0
for msg in (response.messages or []):
    role = getattr(msg, "role", None)
    if role == "tool":
        cycle_count += 1
        if time_to_target == 0 and self.required_files:
            content_str = str(getattr(msg, "content", "") or "")
            if any(req in content_str for req in self.required_files):
                time_to_target = cycle_count
metrics_data["time_to_target"] = time_to_target
```

This is more accurate than using tool_exec because it uses the actual message sequence.

---

## Phase 1b: MCP Warmup

### `src/core/models.py` — McpServerConfig
```python
from dataclasses import dataclass, field

@dataclass
class McpServerConfig:
    tool_name: str
    command: str
    args_template: list[str]
    warmup_call: str | None = None
    warmup_args: dict = field(default_factory=dict)

    def resolve_args(self, worktree_path: str) -> list[str]:
        return [a.replace("{path}", worktree_path) for a in self.args_template]
```

### `agno_runner.py` — warmup before timer in `_run_with_mcp()`
```python
# MCP warmup phase (excluded from duration_sec)
warmup_total = 0.0
for mcp_cfg, session in zip(self.mcp_configs, sessions_list):
    if mcp_cfg.warmup_call:
        t_w = time.time()
        try:
            await session.call_tool(mcp_cfg.warmup_call, mcp_cfg.warmup_args or {})
        except Exception as e:
            _log.warning("MCP warmup call failed for %s: %s", mcp_cfg.tool_name, e)
        warmup_total += time.time() - t_w

start_time = time.time()  # timer starts AFTER warmup
```

For the RunMetrics return, set `warmup_sec=warmup_total`.

The challenge: sessions need to be accessible before building agent. The current code uses AsyncExitStack. Refactor to collect sessions in a list before starting the timer.

---

## Phase 2: Dashboard Update

### `configs/benchmark_weights.yaml`
Add to `all_metrics_weights` section (rebalancing to keep sum = 1.0):

Current sum = 0.18+0.12+0.09+0.09+0.06+0.03+0.03+0.06+0.04+0.08+0.06+0.03+0.03+0.05+0.05 = 1.00

New metrics: avg_tokens_per_tool (0.040), time_to_target (0.030), context_waste_ratio (0.040) = +0.110
Reduce existing: cut total_tokens 0.08→0.05, cost_usd 0.06→0.04, model_calls 0.03→0.02, duration_sec 0.03→0.02 = -0.070 
Also cut errors 0.05→0.04, tool_errors 0.05→0.04 = -0.02 total cut = -0.090 ... need to cut 0.110 total

Let me rebalance:
- total_tokens: 0.080 → 0.040 (-0.040)
- cost_usd: 0.060 → 0.040 (-0.020)
- model_calls: 0.030 → 0.020 (-0.010)
- duration_sec: 0.030 → 0.020 (-0.010)
- errors: 0.050 → 0.030 (-0.020)
- tool_errors: 0.050 → 0.030 (-0.020)
Total cut = 0.120, new metrics add 0.110 → new sum = 1.00 - 0.120 + 0.110 = 0.990
Hmm, let me be more careful:

Current: 0.180+0.120+0.090+0.090+0.060+0.030+0.030+0.060+0.040+0.080+0.060+0.030+0.030+0.050+0.050 = 1.000
Add: avg_tokens_per_tool(0.040) + time_to_target(0.030) + context_waste_ratio(0.040) = +0.110
Must cut: 0.110 from existing
Cut plan:
  total_tokens: 0.080 → 0.050 (-0.030)
  cost_usd: 0.060 → 0.040 (-0.020)
  errors: 0.050 → 0.040 (-0.010)
  tool_errors: 0.050 → 0.040 (-0.010)
  model_calls: 0.030 → 0.020 (-0.010)
  duration_sec: 0.030 → 0.020 (-0.010)
  retrieval_precision: 0.060 → 0.045 (-0.015)
  retrieval_recall: 0.040 → 0.035 (-0.005)
Total cut = 0.111 ≈ close to 0.110 (adjust retrieval_recall to 0.034 or similar)

Actually use clean numbers:
  total_tokens: 0.080 → 0.045 (-0.035)
  cost_usd: 0.060 → 0.040 (-0.020)
  errors: 0.050 → 0.040 (-0.010)
  tool_errors: 0.050 → 0.040 (-0.010)
  model_calls: 0.030 → 0.020 (-0.010)
  duration_sec: 0.030 → 0.020 (-0.010)
  retrieval_precision: 0.060 → 0.050 (-0.010)
  retrieval_recall: 0.040 → 0.035 (-0.005)
Total cut = 0.110 ✓

New sum check:
0.180+0.120+0.090+0.090+0.060+0.030+0.030+0.050+0.035+0.045+0.040+0.020+0.020+0.040+0.040+0.040+0.030+0.040
= 0.180+0.120+0.090+0.090+0.060+0.030+0.030 = 0.600
+ 0.050+0.035 = 0.085
+ 0.045+0.040+0.020+0.020 = 0.125
+ 0.040+0.040 = 0.080
+ 0.040+0.030+0.040 = 0.110
Total = 0.600+0.085+0.125+0.080+0.110 = 1.000 ✓

### `src/features/dashboard_builder.py`
- Add new column fields in Table 1 (leaderboard): `avg_tokens_per_tool`, `time_to_target`, `context_waste_ratio`
- Update `_DEFAULT_ALL_METRICS` with new fields
- Update `_ZERO_OK_LOWER` to include `time_to_target` (0 means not measured, not "never reached") - actually use "lower" normal since 0 means agent didn't use required files at all... keep as lower with min normalization.

---

## Phase 3: Streamlit MVP

### File: `streamlit_app.py` (root)

```python
"""Streamlit dashboard for benchmark results."""
import streamlit as st
...
```

Implementation:
- Sidebar: run selector (dropdown from results/) + pass/fail filter
- Tab 1 - Leaderboard: st.dataframe with columns: config, pass, eval_composite, full_composite, tokens, cost, SPT, TTT, waste%
- Tab 2 - Config Deep Dive:
  - Config selector
  - Radar chart (plotly): 7 judge dimensions vs median
  - Judge Reasoning expanders
  - Code Diff: st.code() with final.patch
  - Agent Timeline: table from agent_messages.json

Add to pyproject.toml:
```toml
streamlit = ">=1.35"
plotly = ">=5.20"
```

---

## Implementation Order

1. `src/core/models.py` — add ProviderConfig, TaskConfig, CodebaseConfig; update RunMetrics + McpServerConfig
2. `src/core/config_loader.py` — add new load functions
3. `configs/provider.yaml` — create
4. `configs/tools.yaml` — create (20 configs without model/max_steps)
5. `configs/tasks/medium.yaml` — create (current task text)
6. `configs/tasks/easy.yaml` — create
7. `configs/tasks/hard.yaml` — create
8. `configs/codebase.yaml` — create
9. `main.py` — add new CLI flags and new-style loading logic
10. `src/orchestrator/benchmark.py` — add `configs` and `required_files` params
11. `src/features/agent_integration/agno_runner.py` — add required_files param + compute agent_cycles, time_to_target, context_waste_ratio, warmup_sec
12. `configs/benchmark_weights.yaml` — add new metric entries (rebalanced)
13. `src/features/dashboard_builder.py` — update defaults + new columns in HTML
14. `streamlit_app.py` — create MVP

## Key Constraints
- NEVER break existing `python main.py --configs configs/benchmark_configs.yaml` flow — backward compat is required
- New-style flags only active if their YAML files exist
- The `--task` string flag stays as string override; new `--task-config` takes YAML path
- `McpServerConfig` is a dataclass: use `field(default_factory=dict)` for `warmup_args`
- `avg_tokens_per_tool` is a `@computed_field` derived from existing fields
- English only in all code/comments
- No markdown docs unless explicitly needed
