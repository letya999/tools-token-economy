# Tools Token Economy Benchmark

**Which tool strategy lets a coding agent solve a task with the fewest tokens?**

This benchmark runs 21 tool configurations against the same coding task and measures success rate, token cost, efficiency (SPT), and 7 LLM-judge quality dimensions. All configs use the same model (`gpt-4.1-mini`) and the same task — only the available tools differ.

## Results snapshot — Hard task, 2026-06-01

**21 configs × 6 repetitions = 126 runs.** Task: add `is_stale` flag to a Polars work-item aging pipeline. 3 files to navigate, strict schema requirement. Total cost: $15.16.

> **Run metadata:** n=6 reps · model=gpt-4.1-mini · task=hard (aging_stale) · 2026-06-01
> Judge model: gpt-5.4-nano. Sorted by avg judge score across 6 reps.

| Config | Tools | Pass | Judge | Avg Tokens | Efficiency |
|---|---|---|---|---|---|
| **04_codex_like** | grep+read+edit | **6/6** | **0.85** | 861K | expensive |
| **20_serena_semble** | serena+semble | 5/6 | **0.79** | 120K | ⭐ best balance |
| 14_repo_map | repo_map+edit | 4/6 | 0.76 | 97K | good |
| **16_serena_only** | serena | **6/6** | 0.68 | **79K** | ⭐ token champion |
| 17_semble_only | semble | 5/6 | 0.58 | 84K | |
| 10_ugrep | ugrep+edit | 4/6 | 0.62 | 1,224K | very expensive |
| 18_rg_repo_map | rg+repo_map | 0/6 | 0.49 | 79K | 0 pass but judge≠0 |
| 19_rg_lsp | rg+lsp | 4/6 | 0.37 | 425K | pass≠quality |
| 03_gemini_like | read_all+repo_map | **0/6** | **0.00** | 419K | total failure |
| 21_bash_only | bash | 0/6 | 0.10 | 85K | can't structure edits |

**Key findings:**
- `serena_only` is the **token-efficiency champion**: 100% pass rate at only 79K avg tokens (11x fewer than codex_like at equal pass rate)
- `serena_semble` offers the best quality/cost balance: judge=0.79 at 120K tokens
- `rg_lsp` and `git_grep` had 67% pass rate but judge score of only 0.37 — they passed tests without truly solving the task
- `rg_repo_map`: 0% pass but judge=0.49 — the agent had the right approach but execution failed
- `gemini_like` (read_all+repo_map): 0% pass, judge=0.00 at 419K tokens — agent entered a read loop and never produced changes

## Results snapshot — Medium task, 2026-05-25

**20 configs, 1 repetition.** Task: fix case-insensitive Bearer token prefix in auth middleware.
14/20 configs passed (70%). Sorted by token efficiency (ascending tokens = more efficient).

> **Run metadata:** n=1 · model=gpt-4.1-mini · task=medium · 2026-05-25

| Config | Tools | Tokens | Cost $ | Pass | Notes |
|---|---|---|---|---|---|
| **10_ugrep** | ugrep + edit | **2,697** | **$0.0018** | ✓ | most efficient |
| **18_rg_repo_map** | rg + repo_map | 3,003 | $0.0020 | ✓ | |
| **07_grep** | grep + edit | 3,439 | $0.0022 | ✓ | |
| **05_read_only** | glob + read | 3,276 | $0.0021 | ✓ | |
| **02_claude_code_like** | glob + rg + edit | 3,559 | $0.0022 | ✓ | |
| 08_git_grep | git_grep + edit | 4,576 | $0.0027 | ✓ | |
| 13_lsp | lsp + edit | 9,994 | $0.0077 | ✓ | |
| 14_repo_map | repo_map + edit | 11,087 | $0.0065 | ✓ | |
| 12_tree_sitter | tree_sitter + edit | 13,469 | $0.0074 | ✓ | |
| 20_serena_semble | serena+semble | 32,747 | $0.0188 | ✓ | |
| 03_gemini_like | read_all+repo_map | 175,208 | $0.1015 | ✗ | context explosion |

**Key finding:** On medium tasks, lightweight grep-style tools dominate. On hard tasks (see above), semantic tools (serena) take the lead. Task complexity is the key differentiator.

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
