# Agent Instructions: Tools Token Economy Benchmark

## For AI Agents — Two-Phase Protocol

Before doing any coding work on this repo, follow this two-phase protocol:

### Phase 1 — Setup (run once, or after environment changes)
```bash
wsl bash -c "cd /mnt/c/Users/User/a_projects/tools_token_economy && uv run python main.py --setup"
```
This runs 6 stages: platform detection → system tools → Python version → target repo sync →
preflight checks (tool CLIs, API keys, smoke tests) → dry-run of all 20 configs.

**Success looks like**: every stage prints `[PASS]`. The last line is:
```
  Setup complete. Run `python main.py` to start the benchmark.
```

**If a stage fails**: fix the reported issue (install missing tool, set env var, etc.)
and re-run `--setup`. Do not proceed to Phase 2 until all stages pass.

### Phase 2 — Run benchmark
```bash
wsl bash -c "cd /mnt/c/Users/User/a_projects/tools_token_economy && uv run python main.py"
```
**Success looks like**: 20 configs run, each logs `Config XX done. Success=True/False`.
Results appear in `results/run_TIMESTAMP_*/metrics.json`.

Key metrics to check after the run:
- `execution_result`: should be `passed` or `failed`, never `env_error`
- `success`: True = agent completed the task
- `task_solved_score`: LLM judge score 0.0–1.0
- `retrieval_precision` / `retrieval_recall`: file navigation efficiency

### Phase 3 — Analyse results (optional)
```bash
# Interactive 8-tab Streamlit dashboard (recommended)
uv run streamlit run streamlit_app.py
# Opens at http://localhost:8501

# Static HTML dashboard (no server)
uv run python main.py --dashboard
```

**Dashboard tabs**: Leaderboard · Config Explorer · Charts · Run Info · Weights · Glossary · Config Deep Dive · All Metrics.
Language switching (EN/RU) is available in the sidebar.

---

You are an expert AI agent working on a research framework designed to evaluate the token-efficiency and task-efficiency of coding agents.

## Core Mandates
- **Clean Architecture**: Strictly maintain separation between layers (Core, Features, Orchestrator).
- **Vertical Feature Sliced Design (VFSD)**: Organize code by features (e.g., isolation, telemetry, tools) rather than technical roles.
- **TDD First**: Every feature must have a corresponding test in `tests/` before implementation.
- **Adherence to Policies**: You MUST follow all standards defined in **[POLICIES.md](docs/POLICIES.md)**, especially regarding security and "Hardcore" linting.
- **WSL2 Consistency**: All agent execution and tool testing happen in WSL2 Ubuntu. Ensure paths are handled correctly across Win/WSL boundaries.
- **Token Economy**: The goal is to measure `success_per_token`. Minimize context bloat.

## Workflow
1. **Research**: Map the codebase using symbolic tools (Serena/Semble) or grep.
2. **Strategy**: Propose a plan that respects the [ARCHITECTURE.md](docs/ARCHITECTURE.md).
3. **Execution**: Implement surgical changes. Use `uv run pytest` for validation.
4. **Telemetry**: Ensure all new tools/actions correctly report token usage to `RunMetrics`.

## Technical Stack
- **Runtime**: Python 3.12+ (WSL2 Ubuntu)
- **Package Manager**: `uv` (use `uv run` for all commands)
- **Data Models**: `pydantic` v2 (refer to [SDD.md](docs/SDD.md) for schemas)
- **Tokenization**: `tiktoken` (fallback) & Provider-specific metrics (primary)
- **Agent Runner**: `OpenCode` CLI (subprocess wrapper)
- **MCP Ecosystem**: Persistent sessions for `Serena` and `Semble`.

## Key Documentation
- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)**: High-level system design and layer responsibilities.
- **[SDD.md](docs/SDD.md)**: Data structures for `AgentConfig`, `RunMetrics`, and `EvalResult`.
- **[ROADMAP.md](docs/ROADMAP.md)**: Project progress and Phase 5 details.

## Tool Registry Guidelines
- All tools must inherit from `BaseTool` in `src.core.tools`.
- Tool outputs must be formatted using `self.format_result()`.
- Semantic tools (Serena/Semble) should use the persistent `McpToolClient`.
