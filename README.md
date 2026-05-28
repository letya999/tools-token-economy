# Tools Token Economy Benchmark

Measures how efficiently coding agents use context tokens to solve tasks.
Runs 20 configurations (different tool sets) against the same task and compares:
**success rate**, **tokens per success**, **cost**, and 7 LLM-judge scores.

---

## Quick Start

### 1. Clone and enter the repo
```bash
git clone <repo-url>
cd tools_token_economy
```

### 2. Run setup (checks environment, installs deps, dry-runs all 20 configs)
```bash
wsl bash -c "cd /mnt/c/Users/User/a_projects/tools_token_economy && uv run python main.py --setup"
```
Expected: all stages print `[PASS]`. If any stage fails, fix the reported issue and re-run.

### 3. Run the benchmark
```bash
wsl bash -c "cd /mnt/c/Users/User/a_projects/tools_token_economy && uv run python main.py"
```
Results are saved to `results/run_TIMESTAMP_*/metrics.json`.

### 4. View results — interactive Streamlit dashboard (recommended)
```bash
uv run streamlit run streamlit_app.py
```
Opens at `http://localhost:8501`. Features 8 tabs:

| Tab | Description |
|-----|-------------|
| **Leaderboard** | Ranked table: Eval · Tokens · Cost · SPT · TTT · Waste% · Cycles |
| **Config Explorer** | Per-config expandable view: metrics + judge scores + reasoning + diff + agent timeline |
| **Charts** | Bar chart (metric × configs × color grouping) + Radar (≤5 configs × ≤12 dimensions) |
| **Run Info** | Provider, model, task description, codebase info, all 20 tool configs |
| **Weights** | Visual breakdown of eval and all-metrics composite weights |
| **Glossary** | Searchable reference for all 35 metrics, eval scores, and indicators |
| **Config Deep Dive** | Radar chart vs median + reasoning expanders + code diff + timeline |
| **All Metrics** | Every RunMetrics field for every config, sortable + statistical summary |

Language switching (EN/RU) is available in the sidebar.

### 4b. View results as static HTML dashboard
```bash
uv run python main.py --dashboard
```
Generates `results/dashboard_TIMESTAMP.html` — no server required.

---

## Other Commands

| Command | Description |
|---------|-------------|
| `python main.py --dry-run` | Mock run — no API calls, verifies all 20 configs load |
| `python main.py --config-ids 02_claude_code_like` | Run a single config |
| `python main.py --retry-failed` | Re-run only configs that failed in the last run |
| `python main.py --doctor` | Infrastructure health check |
| `python main.py --setup` | Full setup pipeline |

---

## Adding a New Benchmark Config

1. Open `configs/benchmark_configs.yaml`
2. Add a new entry under `configs:` with a unique `id`, `name`, `archetype`, and `tools` list
3. Available tools: `read`, `write`, `patch`, `glob`, `rg`, `grep`, `git_grep`, `ugrep`,
   `ast_grep`, `semgrep`, `tree_sitter`, `lsp_symbols`, `repo_map`, `simple_rag`,
   `serena`, `semble`, `shell`, `insert_after`
4. Run `python main.py --dry-run --config-ids your_new_id` to verify it loads

---

## Architecture

```
src/
  core/           # Models (RunMetrics, BenchmarkMeta, AgentConfig), config loader
  features/       # Isolation, execution validator, LLM judge, preflight, tool registry
  orchestrator/   # BenchmarkOrchestrator — wires everything together
configs/
  provider.yaml        # Model provider settings (model, max_steps, temperature)
  tools.yaml           # 20 tool strategies (no model field — inherited from provider)
  tasks/medium.yaml    # Task definition (description, test_cmd, required_files)
  codebase.yaml        # Target repository (path, github_url, install_cmd)
  benchmark_weights.yaml  # Scoring weights for eval and all-metrics composites
streamlit_app.py  # Interactive 8-tab dashboard (uv run streamlit run streamlit_app.py)
results/          # Output: per-run metrics.json, agent_messages.json, final.patch
tests/            # Unit tests (run with: uv run pytest tests/)
```

See `docs/ARCHITECTURE.md` for full design details.

---

## Prerequisites

- Python 3.13+, `uv`
- WSL2 Ubuntu (benchmark runs in WSL, paths auto-converted)
- `rg` (ripgrep): `sudo apt install ripgrep`
- API key: `OPENAI_API_KEY` in `.env` (for agent + judge)
