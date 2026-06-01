# Implementation Plan: Benchmark Improvements
Date: 2026-06-01

## Context & Terminology

This project benchmarks coding agent tool strategies. Key terms used throughout the codebase and this plan:

| Term | Definition |
|------|-----------|
| **Task** | A coding problem: description, target_file, test_cmd, difficulty. e.g. `aging_stale` |
| **Codebase** | Target repository where agent makes changes. e.g. `process_metrics_platform_v2` |
| **Config** | One toolset + agent parameters. 21 configs total. e.g. `05_read_only`, `08_git_grep` |
| **Run** | Single execution of one Config on one Task. Folder `run_{session}_{rep}_{config_id}` |
| **Rep** (Repetition) | One full pass over all Configs. r001, r002, ... r006 |
| **Suite** | One Rep = 1 pass × 21 Configs × 1 Task. **Budget unit: $5 per Suite** |
| **Session** | Full series = N Reps × M Configs. File `session_*_meta.json` |
| **Session budget** | suite_budget × n_reps (e.g. $5 × 6 = $30) |

Budget hierarchy:
- `max_cost_usd_per_agent_run = 0.40` (hard cap per Run for agent)
- `max_cost_usd_per_judge_run = 1.00` (hard cap per Run for judge)
- `max_cost_usd_per_suite = 5.00` (per Rep/Suite = 21 Runs)
- Session budget (computed) = `max_cost_usd_per_suite × n_reps`

CostGuard MUST reset after each Suite (Rep) completes — it is NOT cumulative across the whole Session.

---

## Block 1 — Budget & Cost Tracking

### 1.1 Capture `cache_read_tokens` from Agno
**File:** `src/features/agent_integration/agno_runner.py`

In `_extract_metrics_from_response()`, after reading `response.metrics.input_tokens` and `output_tokens`, also extract prompt cache hit tokens:
```python
metrics_data["cache_read_tokens"] = (
    getattr(response.metrics, "prompt_cache_hit_tokens", 0) or
    getattr(response.metrics, "cache_read_input_tokens", 0) or
    getattr(response.metrics, "cached_tokens", 0) or 0
)
```
This fixes the ~2x cost overestimation: OpenAI bills cached tokens at $0.10/1M, our formula was charging all input at $0.40/1M because `cache_read_tokens` was always 0.

### 1.2 Judge cost tracking + $1/Run limit
**Files:** `src/core/models.py`, `src/features/llm_judge.py`, `src/features/cost_guard.py`, `src/orchestrator/benchmark_runner.py`

**`src/core/models.py` — RunMetrics:**
Add fields:
```python
judge_cost_usd: float = 0.0
judge_input_tokens: int = 0
judge_output_tokens: int = 0
judge_skipped: bool = False
```

**`src/features/llm_judge.py`:**
- Track tokens and cost for each of the 7 judge calls using gpt-5.4-nano pricing ($0.20 input / $1.25 output per 1M)
- Return `judge_totals: dict` with `{judge_cost_usd, judge_input_tokens, judge_output_tokens}` alongside existing scores
- LLMJudge.__init__ accepts `max_judge_usd: float = 1.0`
- If cumulative judge cost for this Run exceeds `max_judge_usd`, stop calling judge, set `judge_skipped=True`, use scores collected so far (or 0.0 for remaining criteria)

**`src/features/cost_guard.py`:**
- Add `max_judge_usd_per_run: float = 1.0` to `__init__`
- Add `record_judge(config_id: str, judge_cost: float, judge_tokens: int)` method
- Add `suite_judge_cost: float = 0.0` tracked separately
- In `reset_suite()`: reset `total_cost = 0.0`, `suite_judge_cost = 0.0`, keep `session_total_cost` accumulating

### 1.3 Correct Suite budget semantics (CRITICAL — fixes early abort at r004_13)
**Files:** `src/core/models.py`, `src/features/cost_guard.py`, `src/orchestrator/benchmark_runner.py`

**`src/core/models.py`:**
- `BenchmarkMeta.max_cost_usd_suite: float = 5.0` — this is per-Suite (per-Rep), NOT per-Session
- Add `BenchmarkMeta.max_cost_usd_per_agent_run: float = 0.40`
- Add `BenchmarkMeta.max_cost_usd_per_judge_run: float = 1.00`

**`src/features/cost_guard.py`:**
- Add `reset_suite()` method: resets `total_cost = 0.0` (suite-level counter), increments `session_cost += total_cost`
- Add property `session_total_cost: float` — accumulates across all Suites in Session
- `check_suite_budget()` checks against `max_suite_usd` (per-Suite), not session total

**`src/orchestrator/benchmark_runner.py`:**
- Remove hardcoded `max_suite_usd=8.0`, `max_config_usd=0.40`, `max_tokens_per_config=600_000`
- Read all limits from `self.benchmark_meta` (BenchmarkMeta)
- After completing each Rep (all 21 configs), call `self.cost_guard.reset_suite()`
- Log session_total_cost at end

---

## Block 2 — LLM Judge Logging

### 2.1 Save `judge_log.json` per Run
**File:** `src/features/llm_judge.py`

After all 7 judge calls complete, write `{run_dir}/judge_log.json`:
```json
[
  {
    "criterion": "task_solved",
    "prompt": "...",
    "response_raw": "...",
    "score": 0.8,
    "reasoning": "...",
    "input_tokens": 1200,
    "output_tokens": 150,
    "cost_usd": 0.000432,
    "timestamp": "2026-06-01T01:23:45"
  },
  ... (7 entries total)
]
```
`run_dir` is passed to `LLMJudge` — add `run_dir: str | None = None` parameter to `__init__`. Only write if `run_dir` is not None.

### 2.2 Show judge log in dashboard
**File:** `streamlit_app.py`

In Tab "Run Info" (tab4): add section "Вызовы судьи / Judge Calls".
- Load `judge_log.json` if present for selected Run
- Show per-criterion expander: criterion name, score badge, reasoning, tokens, cost_usd
- Show total judge cost summary

---

## Block 3 — Task info in Dashboard

### 3.1 Store task metadata in session meta
**File:** `src/orchestrator/benchmark_runner.py` and/or `src/orchestrator/session_manager.py`

When writing `session_*_meta.json`, include:
```json
{
  "task_name": "aging_stale",
  "task_description": "Add is_stale boolean flag to work item aging calculation...",
  "task_difficulty": "hard",
  "task_test_cmd": "uv run --extra dev pytest tests/unit/test_aging.py -q",
  "codebase_name": "process_metrics_platform_v2",
  "model": "gpt-4.1-mini",
  "judge_model": "gpt-5.4-nano"
}
```

### 3.2 Show task info in sidebar and header
**File:** `streamlit_app.py`

- In sidebar below session selector: show task_name, difficulty badge (🔴 hard / 🟡 medium / 🟢 easy), codebase_name
- Leaderboard header: `Leaderboard — aging_stale (hard) — 20260601_005902`
- If session meta lacks task fields, gracefully fall back to "—"

### 3.3 Investigate zero SPT values
**Files:** results/run_20260601_005902_*/metrics.json

Check actual values of `task_solved_score`, `success`, `judge_reasoning_task` across the 76 runs.
- If all `task_solved_score = 0.0` AND `success = False`: agent truly failed all tasks (aging_stale is hard)
- If `task_solved_score = 0.0` but `success = True`: judge didn't score (empty judge call / wrong model)
- Fix: ensure `net_spt` fallback uses binary `success` when `task_solved_score = 0.0` (this exists in code but verify it works)
- In dashboard: if all SPT = 0, show warning "Все конфигурации не решили задачу / судья не запускался" with suggestion

---

## Block 4 — Streamlit Localization (Russian)

### 4.1 Translate missing strings in `_STRINGS["ru"]`
**File:** `streamlit_app.py`

Missing Russian translations to add:
- Glossary tab content: all metric descriptions currently only in English
- Section headers: "Ranked Results (Significance-Aware)" → "Ранжированные результаты (с учётом значимости)"
- "Not Ranked (Unstable / Insufficient Data)" → "Не ранжированы (нестабильные / недостаточно данных)"
- "SINGLE RUN SESSION" warning
- Download button "Download Aggregated Results (CSV)"
- Stat Summary section
- "Judge Calls" section
- Status values: `ok` → `норма`, `low_confidence` → `низкая уверенность`, `unstable` → `нестабильно`, `insufficient_data` → `мало данных`
- Column rename map for Russian mode

### 4.2 Localize dataframe column names
**File:** `streamlit_app.py`

Before each `st.dataframe()` call, apply `df.rename(columns=_column_names[lang])` where `_column_names` dict maps technical names to display names per language:
- `rank` → "Место" / "Rank"
- `tie_band` → "Группа" / "Band"
- `config_name` → "Конфигурация" / "Config"
- `_validity_status` → "Статус" / "Status"
- `n_runs_completed` → "Ранов" / "Runs"
- `eval_score` → "Оценка" / "Score"
- `total_tokens` → "Токены" / "Tokens"
- `cost_usd` → "Стоимость $" / "Cost $"

---

## Block 5 — Streamlit Windows Startup Fix

### 5.1 Fix UTF-8 BOM in Streamlit config.toml
**Action:** Create/overwrite `~/.streamlit/config.toml` without BOM.
This file is in WSL home directory: `/home/artem/.streamlit/config.toml`
Write it with proper UTF-8 (no BOM). Current content causes `TomlDecodeError` on every startup (non-fatal but noisy).

### 5.2 Add Windows launch script
**File:** `scripts/start_dashboard_win.bat`
Content: launches Streamlit using `.venv\Scripts\streamlit.exe` directly (bypasses `uv run` which needs `pyvenv.cfg`):
```bat
@echo off
cd /d %~dp0..
.venv\Scripts\streamlit.exe run streamlit_app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true
```

### 5.3 Add `pyvenv.cfg` generation to setup
**File:** `scripts/setup_windows.bat` (create if not exists) or add to Makefile
After `uv sync`, if `.venv\pyvenv.cfg` is missing, generate it pointing to Python 3.13:
```
home = C:\Users\User\AppData\Local\Programs\Python\Python313
include-system-site-packages = false
version = 3.13.13
```
Also add `.venv/pyvenv.cfg` to `.gitignore` (machine-specific path).

### 5.4 Results path diagnostic in sidebar
**File:** `streamlit_app.py`
Add `st.sidebar.caption(f"📁 {_ROOT / 'results'}")` so user can verify the dashboard is reading from the correct path (important when switching between WSL-run and Windows-run benchmarks).

---

## Block 6 — Session Meta Accuracy & Coverage Display

### 6.1 Fix `n_completed` and `status` in session meta
**File:** `src/orchestrator/session_manager.py` and/or `benchmark_runner.py`

Current bug: session meta shows `n_completed: 6, status: complete` even when only 76/126 runs finished.

Fix session meta fields:
- `n_runs_expected`: `n_reps × n_configs` (e.g. 126)
- `n_runs_completed`: actual count of finished Run folders with `metrics.json`
- `n_reps_expected`: configured reps (e.g. 6)
- `n_reps_completed`: how many full Reps finished (e.g. 3)
- `coverage_pct`: `n_runs_completed / n_runs_expected × 100`
- `status`: `"complete"` only if `n_runs_completed == n_runs_expected`, else `"partial"`

### 6.2 Coverage display in sidebar
**File:** `streamlit_app.py`

Replace current `"📊 {n_runs} runs · p75 aggregation"` with:
```
📊 76/126 ранов завершено
   3/6 Rep полных · coverage 60%
   p75 агрегация
```
Color-code: green if coverage >= 80%, yellow if 50-80%, red if < 50%.

---

## Block 7 — Terminology in Documentation

### 7.1 Add Terminology section to README.md
**File:** `README.md`
Add section "## Terminology" with the table from this plan (Task, Codebase, Config, Run, Rep, Suite, Session, Sweep, Benchmark) and the budget hierarchy diagram.

### 7.2 Update AGENTS.md
**File:** `AGENTS.md`
Replace vague phrases like "benchmark run", "config run", "test run" with precise terms from the terminology table.

### 7.3 Terminology tab in dashboard
**File:** `streamlit_app.py` — Glossary tab (tab6)
Add "Терминология / Terminology" section at the TOP of the Glossary tab, before metric definitions. Show the hierarchy: Task → Config → Run → Suite (Rep) → Session.

---

## Files to Create/Modify Summary

| File | Action | Block |
|------|--------|-------|
| `src/features/agent_integration/agno_runner.py` | Modify: add cache_read_tokens extraction | 1.1 |
| `src/core/models.py` | Modify: add judge_* fields to RunMetrics, fix BenchmarkMeta defaults | 1.2, 1.3 |
| `src/features/llm_judge.py` | Modify: track judge tokens/cost, write judge_log.json, accept run_dir | 1.2, 2.1 |
| `src/features/cost_guard.py` | Modify: add reset_suite(), judge tracking, session_total | 1.2, 1.3 |
| `src/orchestrator/benchmark_runner.py` | Modify: remove hardcoded limits, call reset_suite(), pass task metadata to session | 1.3, 3.1 |
| `src/orchestrator/session_manager.py` | Modify: fix n_completed, status, add coverage fields | 3.1, 6.1 |
| `streamlit_app.py` | Modify: task info sidebar/header, judge log display, localization, coverage, terminology tab | 2.2, 3.2, 4.1, 4.2, 5.4, 6.2, 7.3 |
| `scripts/start_dashboard_win.bat` | Create: Windows launch script for Streamlit | 5.2 |
| `scripts/setup_windows.bat` | Create/modify: pyvenv.cfg generation | 5.3 |
| `.gitignore` | Modify: add `.venv/pyvenv.cfg` | 5.3 |
| `README.md` | Modify: add Terminology section | 7.1 |
| `AGENTS.md` | Modify: replace vague terms with precise terminology | 7.2 |

---

## Implementation Order (suggested)

1. **Block 1.3** — Fix CostGuard suite semantics (prevents early abort)
2. **Block 3.3** — Investigate zero SPT in existing data (diagnostic only)
3. **Block 3.1 + 3.2** — Task info in session meta + dashboard
4. **Block 1.1** — cache_read_tokens (fix cost formula)
5. **Block 1.2** — Judge cost tracking + limit
6. **Block 2.1 + 2.2** — Judge log file + dashboard display
7. **Block 5** — Windows Streamlit fixes
8. **Block 4** — Localization
9. **Block 6** — Session meta accuracy
10. **Block 7** — Documentation terminology
