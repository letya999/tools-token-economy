# Tools Token Economy Benchmark

**Which tool strategy lets a coding agent solve a task with the fewest tokens?**

This benchmark runs 21 tool configurations against the same coding task and measures success rate, token cost, efficiency (SPT), and 7 LLM-judge quality dimensions. All configs use the same model (`gpt-4.1-mini`) and the same task — only the available tools differ.

## Results snapshot — run 2026-05-30

20 of 21 configs passed (95%). Key findings:

> **Run metadata:** n=1 · model=gpt-4.1-mini · task=medium · 2026-05-30
> Results below show selected configs sorted by SPT. Full interactive table in the dashboard.

| Config | Tools | Tokens | Cost $ | SPT | Waste% |
|---|---|---|---|---|---|
| **08_git_grep** | git\_grep + edit | 12,431 | **$0.0027** | **80.4** | 85.7% |
| **02_claude_code_like** | glob + rg + edit | 17,139 | $0.0031 | 58.3 | 75.4% |
| **07_grep** | grep + edit | 20,393 | $0.0036 | 49.0 | 80.3% |
| 04_codex_like | grep + read + edit | 36,263 | $0.0071 | 27.6 | 34.3% |
| 10_ugrep | ugrep + edit | 51,462 | $0.0080 | 19.4 | 100.0% |
| 05_read_only | glob + read + edit | 59,890 | $0.0086 | 16.7 | 59.0% |
| 14_repo_map | repo\_map + edit | 177,189 | $0.0291 | 5.6 | 97.6% |
| 01_cursor_like | repo\_map + RAG + shell | 282,889 | $0.0503 | 3.5 | 98.2% |
| 06_read_all | read\_all + edit | 682,478 | $0.0877 | 1.5 | 85.8% |

> **SPT** = Score Per 1K Tokens (higher = more efficient). **Waste%** = fraction of context irrelevant to the task.
> `03_gemini_like` (read\_all + repo\_map) used 682K tokens — agent entered a read loop. Excluded from table due to extreme token cost distorting scale.

**Bottom line:** Targeted search tools (`git_grep`, `rg`, `grep`) use significantly fewer tokens than bulk-read strategies. In this single run, `git_grep` achieved the best SPT score (12K tokens vs 682K for `read_all`). Multi-run aggregation needed for statistical confidence.

---

## Screenshots

| Leaderboard | Config Explorer |
|---|---|
| ![leaderboard](docs/screenshots/01_leaderboard.png) | ![explorer](docs/screenshots/03_config_explorer.png) |

| Charts | Config Deep Dive |
|---|---|
| ![charts](docs/screenshots/02_charts.png) | ![deepdive](docs/screenshots/05_deep_dive.png) |

| Run Info | All Metrics |
|---|---|
| ![runinfo](docs/screenshots/04_run_info.png) | ![allmetrics](docs/screenshots/06_all_metrics.png) |

---

## What it measures

Each run captures:

- **success** — did the agent's patch pass all tests?
- **eval\_score** — composite score (success × judge scores × efficiency penalties)
- **SPT** — `success / (total_tokens / 1000)` — the primary efficiency metric
- **Waste%** — share of context tokens that were read but not used in the final patch
- **TTT** — time-to-target: how many cycles before the agent first touched the right file
- **7 LLM-judge dimensions**: task\_solved, correctness, tool\_correctness, context\_quality, minimality, pattern\_adherence, tool\_sequence

The benchmark uses a real Go codebase ([process\_metrics\_platform\_v2](https://github.com/letya999/process_metrics_platform_v2)) and a real task: fix a case-insensitive Bearer token prefix bug. The agent must find the right function, patch it, and add a regression test — all verified by `pytest`.

---

## Quick start

### 1. Clone and enter the repo
```bash
git clone https://github.com/letya999/tools-token-economy
cd tools-token-economy
```

### 2. Configure
```bash
cp .env.example .env  # add OPENAI_API_KEY
```

### 3. Setup (checks environment, installs deps, dry-runs all 21 configs)
```bash
wsl bash scripts/run_wsl.sh --dry-run
```
Expected: every stage prints `[PASS]`.

### 4. Run the benchmark
```bash
wsl bash scripts/run_wsl.sh
```
Results: `results/run_TIMESTAMP_*/metrics.json`

### 5. View the dashboard
```bash
# Windows (recommended)
python -m streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8501

# or via uv in WSL
uv run streamlit run streamlit_app.py --server.address 0.0.0.0
```
Opens at `http://localhost:8501` — 8 tabs, EN/RU language toggle.

---

## Dashboard tabs

| Tab | What you get |
|---|---|
| **Leaderboard** | Ranked table: Pass · Eval · Tokens · Cost · SPT · TTT · Waste% · Cycles |
| **Config Explorer** | Per-config expandable cards: scores + judge reasoning + code diff + agent timeline |
| **Charts** | Bar chart (any metric × configs) + Radar (up to 5 configs × 12 dimensions) |
| **Run Info** | Model, task description, codebase details, all 21 tool configs |
| **Weights** | Visual breakdown of eval and composite metric weights |
| **Glossary** | Searchable definitions for all 35 metrics and score dimensions |
| **Config Deep Dive** | Radar vs median + full judge reasoning + diff + per-step timeline |
| **All Metrics** | Every RunMetrics field for every config, sortable + statistical summary |

---

## Tool configs

21 configurations across 6 archetypes:

| Archetype | Configs | Philosophy |
|---|---|---|
| **cursor** | 01 | Repo map + RAG for broad context (cursor-inspired archetype) |
| **claude** | 02 | Glob + ripgrep for surgical search (claude-inspired archetype) |
| **gemini** | 03 | Read all + rg (context-first, gemini-inspired archetype) |
| **codex** | 04 | Grep + read (classic Unix, codex-inspired archetype) |
| **ablation** | 05–15 | One search tool at a time (glob, read\_all, grep, git\_grep, rg, ugrep, ast\_grep, tree\_sitter, LSP symbols, repo\_map, simple\_RAG) |
| **semantic** | 16–17 | Serena MCP / Semble MCP (semantic code understanding) |
| **hybrid** | 18–20 | Combinations (rg+repo\_map, rg+LSP, Serena+Semble) |
| **minimal** | 21 | Bash only — no specialised tools |

> Archetype names reflect the tool *philosophy* associated with each coding assistant, not a benchmark of the product itself. Actual Cursor, Claude Code, Gemini, and Codex behavior differs.

---

## Other commands

| Command | Description |
|---|---|
| `python main.py --dry-run` | Verify all 21 configs load (no API calls) |
| `python main.py --config-ids 02_claude_code_like` | Run a single config |
| `python main.py --config-ids 02,08,13` | Run specific configs |
| `python main.py --retry-failed` | Re-run only failed configs into the same results folder |
| `python main.py --runs 5` | Multi-run (p75 aggregation for statistical stability) |
| `python main.py --doctor` | Infrastructure health check |
| `python main.py --dashboard` | Generate static HTML dashboard (no server needed) |

---

## Architecture

```
src/
  core/           # Models (RunMetrics, BenchmarkMeta, AgentConfig), config loader
  features/       # Isolation, LLM judge, preflight, tool registry, metrics aggregator
  orchestrator/   # BenchmarkOrchestrator — wires everything together
configs/
  provider.yaml         # Model provider settings (model, max_steps, temperature)
  tools.yaml            # 21 tool strategies
  tasks/medium.yaml     # Task definition (description, test_cmd, required_files)
  codebase.yaml         # Target repository config
  benchmark_weights.yaml # Scoring weights
streamlit_app.py   # 8-tab interactive dashboard
results/           # Per-run output: metrics.json, agent_messages.json, final.patch
tests/             # Unit tests (pytest)
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for full design details and [`AGENTS.md`](AGENTS.md) for AI agent instructions.

---

## Terminology

| Term | Definition |
|------|-----------|
| **Task** | A coding problem: description, target_file, test_cmd, difficulty. e.g. `aging_stale` |
| **Codebase** | Target repository where agent makes changes. e.g. `process_metrics_platform_v2` |
| **Config** | One toolset + agent parameters. 21 configs total. e.g. `05_read_only`, `08_git_grep` |
| **Run** | Single execution of one Config on one Task. Folder `run_{session}_{rep}_{config_id}` |
| **Rep** (Repetition) | One full pass over all Configs. r001, r002, ... r006 |
| **Suite** | One Rep = 1 pass × 21 Configs × 1 Task. **Budget unit: $5 per Suite** |
| **Session** | Full series = N Reps × M Configs. File `session_*_meta.json` |

### Budget Hierarchy
- **$5.00 per Suite (Rep)**: 21 runs budget.
- **$0.40 per Agent Run**: Hard cap for agent tokens.
- **$1.00 per Judge Run**: Hard cap for judge calls.

---

## Prerequisites

- Python 3.13+, `uv`
- WSL2 Ubuntu (agent execution runs in WSL)
- `rg` (ripgrep): `sudo apt install ripgrep`
- `OPENAI_API_KEY` in `.env`
