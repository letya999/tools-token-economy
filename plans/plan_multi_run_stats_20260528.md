# Plan: Multi-Run Statistical Benchmark

**Date:** 2026-05-28  
**Goal:** Add `--runs N` flag that repeats the full 20-config sweep N times, stores all repetitions in one session folder, aggregates by p75 in the dashboard, and documents how to extend configs/tools.

---

## Files to CREATE

### `src/features/multi_run.py`
New module. Percentile aggregation logic, decoupled from dashboard and aggregator.

```
Functions:
  list_sessions(results_dir) -> list[dict]
    - Scans results/ for session_*_meta.json files
    - Returns list of {session_id, n_runs, n_completed, provider, task, percentile, start_time}
    - Also returns "single" pseudo-sessions for un-sessionized run_* folders (backward compat)

  aggregate_session(results_dir, session_id, percentile=75) -> dict[config_id, dict]
    - Finds all folders matching run_{session_id}_r*_{config_id}/metrics.json
    - Groups by config_id
    - For each numeric metric: computes p25, p50 (median), p75, mean, std, n
    - For boolean metric success: computes success_rate = mean(success)
    - Returns: {config_id: {metric: p75_value, ...metadata: {n, p25, median, mean, std}}}

  write_session_meta(results_dir, session_id, meta_dict)
    - Writes results/session_{session_id}_meta.json
    - Called by orchestrator at session start and updated at end

NUMERIC_METRICS constant: list of all float/int fields in RunMetrics to aggregate
```

---

## Files to MODIFY

### `main.py`
Add ONE new argument to argparse:
```
--runs N    (int, default=1)
            Number of full benchmark repetitions (runs) to execute.
            When N>1: all reps share a session ID, results are stored as
            run_{session_id}_r{rep:03d}_{config_id}/, and the dashboard
            shows p75 aggregates with a "N runs · p75" badge.
```
Pass `n_runs=args.runs` to `BenchmarkOrchestrator(...)`.
Do NOT add --percentile (hardcode p75 as default, can be added later).

---

### `src/orchestrator/benchmark.py`
Changes to `BenchmarkOrchestrator`:

**`__init__`**: accept `n_runs: int = 1`. Store as `self.n_runs`.

**`run_suite()`**: 
```
If n_runs == 1:
    behavior unchanged — timestamp = now, run_id = run_{timestamp}_{config_id}
    no session meta written

If n_runs > 1:
    session_id = time.strftime("%Y%m%d_%H%M%S")  # fixed for all reps
    Write session_meta to results/ at start: {n_runs, provider, model, task, codebase, percentile=75, start_time, n_completed=0}
    for rep in range(1, n_runs+1):
        for config in configs:
            run_id = f"run_{session_id}_r{rep:03d}_{config.id}"
            _run_single_config(config, run_id, ...)
        Update session_meta: n_completed = rep
    Write final session_meta: end_time, status="complete"
    Call generate_session_rankings(session_id) from aggregator
```

**`_run_single_config()`**: no changes needed — run_id is passed in.

---

### `src/features/metrics_aggregator.py`
Add two new methods (do NOT remove existing ones):

```python
def generate_session_rankings(self, session_id: str, percentile: int = 75) -> str:
    """Aggregate N reps of session_id at given percentile and print ranking table."""
    from src.features.multi_run import aggregate_session
    agg = aggregate_session(self.results_base_dir, session_id, percentile)
    # Sort by aggregated task_solved_score desc, then success_rate desc, then total_tokens asc
    # Write to results/RANKINGS_{session_id}_p{percentile}.md
    # Return markdown string

def list_sessions(self) -> list[dict]:
    """Return metadata for all known sessions in results dir."""
    from src.features.multi_run import list_sessions
    return list_sessions(self.results_base_dir)
```

---

### `streamlit_app.py`
The dashboard needs 4 additions:

**1. Session detection in sidebar Run selector:**
```
Current logic: list timestamps from run_* folder names
New logic:
  - load sessions from session_*_meta.json (multi-run sessions)
  - load "single" runs (run_* folders NOT belonging to a session)
  - Sidebar label: "Run / Session"
  - Multi-run sessions displayed as: "2026-05-28 14:30  (10 runs)"
  - Single runs displayed as before: "2026-05-28 14:30"
```

**2. Session badge:**
When a multi-run session is selected, display in sidebar:
```
st.info(f"📊 {n_runs} runs · p75 aggregation")
```
Also add a small badge in the Leaderboard tab header:
```
st.caption(f"Showing p75 across {n_runs} runs (session {session_id})")
```

**3. Data loading — multi-run branch:**
Add helper `_load_session_data(results_dir, session_id) -> list[dict]`:
- Calls `aggregate_session()` from multi_run.py
- Returns list of {config_id, metrics_dict} where metrics_dict contains p75 values
- Adds extra keys: `n_runs`, `success_rate`, `p25_*`, `median_*` for tooltip display

When a single-run timestamp is selected: use existing `_load_run_data()` path unchanged.

**4. Leaderboard extra columns for sessions:**
Add column `N` showing number of successful reps (e.g., "7/10").
Formula: `success_rate * n_runs` rounded to int.
Column header: "Succ/N".

All other tabs (Charts, Deep Dive, etc.) work on p75 values transparently — no special casing needed since they consume the same metrics dict.

---

### `AGENTS.md`
Add two new sections after "Phase 3 — Analyse results":

**Section: Multi-Run Statistical Benchmark**
```
### Multi-Run: Statistical Significance

Run the same benchmark N times to get stable p75 estimates:

    uv run python main.py --runs 10

All 10 repetitions share a session ID. Results are stored as:
    results/run_{session_id}_r001_{config_id}/
    results/run_{session_id}_r002_{config_id}/
    ...
    results/session_{session_id}_meta.json

The Streamlit dashboard auto-detects multi-run sessions and shows p75
aggregated metrics with a "10 runs · p75" badge.

Recommended N per use case:
  - Quick sanity check:      3 runs
  - Exploratory comparison:  5 runs
  - Publication-quality:    10 runs

Note: N=10 with 20 configs = 200 agent runs. Budget: ~$2.75 at gpt-4.1-mini rates
      (based on $0.00275/config median from 2026-05-26 run × 200 = $0.55 for agents
       + ~$1.40 for 7×200=1400 judge calls = ~$2.00 total estimate).
```

**Section: Extending Configs and Tools**
```
### Adding a New Config (Tool Strategy)

1. Open `configs/tools.yaml` (or `configs/benchmark_configs.yaml` in legacy mode)
2. Add a new entry under `configs:`:
   ```yaml
   - id: "21_my_strategy"
     name: "My Strategy"
     archetype: "ablation"         # cursor|claude|gemini|codex|ablation|semantic|hybrid
     tools: ["rg", "read", "write", "patch", "shell"]
     max_steps: 30                 # optional, overrides provider default
   ```
3. Valid tool names: read, read_all, write, patch, insert_after, glob, rg, grep,
   git_grep, ugrep, ast_grep, semgrep, tree_sitter, lsp_symbols, repo_map,
   simple_rag, serena, semble, shell
4. Run `uv run python main.py --dry-run --config-ids 21_my_strategy` to verify it loads.
5. Run `uv run python main.py --config-ids 21_my_strategy` for a real single-config test.


### Adding a New Tool

A tool is a class in `src/features/tool_registry/` that inherits `BaseTool` from
`src/core/tools.py`. Full checklist:

1. Create `src/features/tool_registry/tools/{tool_name}/` directory with:
   - `__init__.py` (empty or re-exports)
   - `validator.py` — optional `ToolValidator` for preflight checks

2. Implement the tool in the appropriate file:
   - File search/grep tools → `src/features/tool_registry/grep_tools.py`
   - File read/write tools → `src/features/tool_registry/basic_tools.py`
   - AST/LSP tools        → `src/features/tool_registry/structural_tools.py`
   - Semantic MCP tools   → `src/features/tool_registry/semantic_tools.py`
   - Shell wrapper        → `src/features/tool_registry/shell_tool.py`

   Minimal tool skeleton:
   ```python
   from src.core.tools import Tool, ToolResult

   class MyTool(Tool):
       name = "my_tool"
       description = "One-line description shown to the agent as tool docstring."

       def execute(self, query: str, path: str = ".") -> ToolResult:
           # all file paths are relative to self.worktree_path
           ...
           return self.format_result(output_str)
   ```
   - `format_result(str)` returns a `ToolResult(output=str)`.
   - If the tool is a shell wrapper: use `ShellExecutor(worktree_path).run(cmd)`.
   - Do NOT raise exceptions — return `self.format_result("Error: ...")` on failure.

3. Register in `src/features/tool_registry/registry.py`:
   ```python
   "my_tool": lambda wt: MyTool(worktree_path=wt),
   ```

4. Write a test in `tests/features/` verifying execute() returns non-empty output.

5. Run `uv run pytest tests/features/test_your_tool.py -q` before committing.

6. Add to `configs/tools.yaml` in one or more configs, or create a new ablation config.

7. Add doctor check in `src/features/doctor.py` if the tool depends on a binary
   (follow the existing pattern for `rg`, `ugrep`, `ast-grep`).
```

---

### `README.md`
Add/update sections:

**After "Other Commands" table** — add:
```
## Multi-Run Benchmark (Statistical Significance)

Run the same benchmark N times to get stable metrics:
    uv run python main.py --runs 10

The dashboard auto-aggregates at p75 and shows a "10 runs · p75" badge.
See AGENTS.md → "Multi-Run Statistical Benchmark" for budget estimates and N recommendations.
```

**Expand "Adding a New Benchmark Config"** section — link to AGENTS.md for the full tool-addition guide:
```
## Extending the Benchmark

### Adding a New Config
[same 4 steps already in README]

### Adding a New Tool
See AGENTS.md → "Adding a New Tool" for the full step-by-step checklist
(tool class skeleton, registry registration, test, doctor check).
```

---

## Implementation Order

| Step | File | What |
|------|------|------|
| 1 | `src/features/multi_run.py` | New module: `NUMERIC_METRICS`, `aggregate_session()`, `list_sessions()`, `write_session_meta()` |
| 2 | `src/orchestrator/benchmark.py` | `n_runs` param, session loop in `run_suite()`, session meta writes |
| 3 | `src/features/metrics_aggregator.py` | `generate_session_rankings()`, `list_sessions()` methods |
| 4 | `main.py` | `--runs N` arg, pass to orchestrator |
| 5 | `streamlit_app.py` | Session detection, multi-run badge, p75 data loading, Succ/N column |
| 6 | `AGENTS.md` | Multi-run + extending sections |
| 7 | `README.md` | Multi-run section + expanding config/tool guide |

---

## Key Invariants

- `--runs 1` (default): ZERO behavior change. No session meta written, run IDs unchanged.
- `--runs N` where N>1: run IDs get `_r{rep:03d}_` infix. Old results without this infix are "single runs" and unaffected.
- Percentile is always 75 (p75). Not configurable from CLI yet — can be added as `--percentile` later.
- `aggregate_session()` must handle partial sessions (some reps missing due to crash) by using whatever data exists, reporting `n` per config.
- Streamlit must NOT break for single-run results (no regression on existing results).
- All new tests go in `tests/features/test_multi_run.py`.

---

## Tests to Write (`tests/features/test_multi_run.py`)

1. `test_aggregate_session_single_rep` — 1 rep, returns same values as raw metrics
2. `test_aggregate_session_p75` — 4 reps with known values, assert p75 is correct
3. `test_aggregate_session_partial` — 3 of 4 reps exist, n=3 returned correctly
4. `test_list_sessions_empty` — empty results dir returns empty list
5. `test_list_sessions_with_meta` — meta file present → returned in list
