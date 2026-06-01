# Plan: HTML Dashboard Template with Composite Scoring

## Goal
Replace the current ad-hoc `_build_dashboard()` in `main.py` with a proper
`DashboardBuilder` module that:
- Generates one HTML dashboard per benchmark run (placed into the results folder)
- For partial re-runs (< N configs), appends to the LAST FULL run's dashboard
- Has 3 tables + filtering + geometric composite score
- Reads weights from a config so they can be changed without code edits

---

## Files to Create / Modify

### 1. NEW: `src/features/dashboard_builder.py`

Core logic module. No external dependencies (pure stdlib + json).

#### Key functions

**`compute_composite(scores: dict[str, float], weights: dict[str, float]) -> float`**
- Weighted geometric mean of all eval score fields
- Formula: `prod((v ** w) for v, w in zip(scores.values(), weights.values())) ** (1/sum(weights.values()))`
- If ANY score is 0.0 → composite = 0.0 (geometric mean collapses on zero)
- Score fields: `task_solved_score`, `tool_correctness_score`, `context_quality_score`,
  `correctness_score`, `minimality_score`, `pattern_adherence_score`, `tool_sequence_score`

**`find_last_full_run_timestamp(results_dir: str, total_configs: int) -> str | None`**
- Scan all `run_*/metrics.json`, group by timestamp (`YYYYMMDD_HHMMSS` part of folder name)
- Return the MOST RECENT timestamp where the group has >= `total_configs` distinct config numbers
- "Full run" = all N config slots covered (01..20 or however many are defined)

**`load_latest_per_config(results_dir: str) -> dict[str, dict]`**
- For each config ID (01..20), find the most recently dated `metrics.json`
- Returns `{config_id: metrics_dict}` with newest run per config
- Merges history: old full run + newer partial re-runs = always freshest data per config

**`generate_dashboard(results_dir: str, output_path: str, weights: dict[str, float] | None = None) -> str`**
- Calls `load_latest_per_config()` to get data
- Computes composite score for each config
- Renders the HTML template (inline, no external files needed)
- Writes to `output_path`, returns the path

#### HTML Template structure (inline Python f-string)

Single self-contained HTML file. No CDN, no external JS/CSS.

**Header:**
- Title, run timestamp, model name
- Filter bar: text input (searches config name), toggle buttons (All / Pass only / Fail only)
- Filter applies to ALL 3 tables simultaneously via JS

**Table 1 — Winners (token efficiency ranking)**
Columns: `#`, `Config Name`, `Pass`, `Composite Score` (bar + value), `Tokens`, `Cost $`, `SPT`, `Duration`
Sorted by composite score descending.
Color coding: green for top 5, yellow for mid, red for bottom / fails.

**Table 2 — Full Evaluation Details**
ALL fields from `RunMetrics`:
- Basic: config_id, success, execution_result, tokens (input/output/tool/total), cost_usd, duration_sec, model_calls, tool_calls
- Retrieval: retrieval_precision, retrieval_recall
- Judge scores (7 cols): task_solved_score, tool_correctness_score, context_quality_score, correctness_score, minimality_score, pattern_adherence_score, tool_sequence_score
- Composite score (computed)
- Infrastructure: files_read, files_changed, patch_lines, errors, tool_errors, made_changes
Each score column has inline mini-bar (CSS, no canvas).
Clicking a column header sorts by that column (JS, pure DOM, no libraries).

**Table 3 — Eval Dimensions & Weights**
Static-ish table showing each judge dimension with:
- Name
- Weight (editable number input, 0.0–2.0)
- Description (what it measures)
- Average score across all configs
When weights are changed → JS recalculates composite for all rows in Table 1 & 2 live.

**JavaScript (inline `<script>`):**
- `filterAll(query, mode)` — filters all 3 tables by config name substring + pass/fail mode
- `sortTable(tableId, colIdx)` — sorts table by column, toggling asc/desc
- `recalcComposite()` — reads current weights, recomputes composite column in Tables 1 & 2
- No external dependencies, no `eval()`, uses `textContent` / `createElement` (no innerHTML with data)

**CSS (inline `<style>`):**
- Dark theme: `background:#0f1117`, text `#e0e0e0`
- Sticky table headers
- Alternating row backgrounds
- Score bar: `<span class="bar">` with percentage width
- Color thresholds: composite >= 0.8 → green, 0.5–0.8 → yellow, < 0.5 → red

---

### 2. MODIFY: `src/orchestrator/benchmark.py`

In the `run()` method, after all configs complete (the final aggregation step):

```python
from src.features.dashboard_builder import generate_dashboard, find_last_full_run_timestamp

total_configs = len(self.configs)
run_timestamp = current_run_timestamp  # already computed

# Determine output location
last_full_ts = find_last_full_run_timestamp(self.results_dir, total_configs)
is_full_run = (run_timestamp == last_full_ts)

if is_full_run:
    out_dir = self.results_dir  # put in results/ root
else:
    # partial re-run: put dashboard in last full run's results dir
    out_dir = self.results_dir  # same root; filename will reflect "updated"

out_path = os.path.join(out_dir, f"dashboard_{run_timestamp}.html")
generate_dashboard(self.results_dir, out_path)
print(f"Dashboard: {out_path}")
```

Also update the per-config `save_run()` call to pass run_timestamp so `find_last_full_run_timestamp` works correctly.

---

### 3. MODIFY: `main.py`

Replace the existing `_build_dashboard()` function body to simply call:
```python
from src.features.dashboard_builder import generate_dashboard
generate_dashboard(results_dir, os.path.join(results_dir, f"dashboard_{ts}.html"))
```

Keep `--dashboard` CLI flag so manual regeneration still works.

---

### 4. DEFAULT WEIGHTS (hardcoded in `dashboard_builder.py`, editable in browser)

```python
DEFAULT_WEIGHTS = {
    "task_solved_score":       2.0,  # most important — did it solve the task?
    "tool_correctness_score":  1.0,
    "context_quality_score":   1.0,
    "correctness_score":       1.5,  # code correctness matters a lot
    "minimality_score":        1.0,
    "pattern_adherence_score": 0.5,
    "tool_sequence_score":     0.5,
}
```

Composite = weighted geometric mean. Displayed in Table 3 as editable inputs.

---

## What NOT to change
- `src/core/models.py` — do NOT add composite as computed_field (it depends on weights which are runtime config)
- `src/features/metrics_aggregator.py` — leave `generate_rankings()` (RANKINGS.md) as-is
- Test files — do not touch

---

## Expected Output
After implementing:
```
results/dashboard_20260528_055639.html   ← generated after partial re-run
results/dashboard_20260527_181911.html   ← generated after that full run (already exists)
```

Dashboard HTML: ~700–900 lines, self-contained, no external deps.
