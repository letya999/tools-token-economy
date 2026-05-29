# Agent Instructions: Tools Token Economy Benchmark

## For AI Agents — Two-Phase Protocol

Before doing any coding work on this repo, follow this two-phase protocol:

### Phase 1 — Setup (run once, or after environment changes)
```bash
wsl bash -c "bash /mnt/c/Users/User/a_projects/tools_token_economy/scripts/run_wsl.sh --setup"
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
wsl bash -c "bash /mnt/c/Users/User/a_projects/tools_token_economy/scripts/run_wsl.sh"
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
