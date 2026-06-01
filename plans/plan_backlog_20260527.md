# Plan: Create BACKLOG.md in project root

## Task
Create a single file `BACKLOG.md` in the project root (`C:\Users\User\a_projects\tools_token_economy\BACKLOG.md`).

The file must document all known issues and planned improvements for the tools_token_economy benchmark project, based on the findings from the first real benchmark run (run_20260527_115254, 19/20 success, $0.19454).

## File to create
`BACKLOG.md` — in the project root (same level as README.md, AGENTS.md, pyproject.toml).

## Content specification

The file must be a structured Markdown backlog with numbered items. Use the following content exactly:

---

# Backlog — Tools Token Economy Benchmark

> Status after first real benchmark run: 19/20 success, $0.19454 total cost (2026-05-27)

---

## 1. Eliminate env_error in worktrees

**Problem**: Every config (19/20) returns `execution_result="env_error"` because `uv` and `pytest` are not in PATH inside git worktrees on NTFS/WSL. The `ExecutionValidator` marks this as `success=True` (environment failed, not agent), so the benchmark does run, but actual test execution is never verified.

**Goal**: Real test pass/fail signal for every config.

**Options to investigate**:
- Remove git worktree isolation entirely. Instead: apply the agent patch to the target repo directly, run tests, then `git checkout -- .` to restore. Simpler, no PATH issues.
- Alternatively: inject the full virtualenv PATH into the worktree subprocess environment explicitly.
- Or: copy the entire `.venv` symlink/directory into the worktree before running tests.

**Acceptance criteria**: `execution_result` is `passed` or `failed` for all configs; `env_error` disappears from results.

---

## 2. Fix 13_lsp config

**Problem**: `13_lsp` is the only hard failure (success=False). The agent ran 3 model+tool calls in 15.5 seconds but made zero file changes (`made_changes=False`, `not_verified`). The LSP symbols tool apparently does not provide enough navigational context for the agent to locate the target file and write changes.

**Actions**:
- Inspect what `lsp_symbols` actually returns for this task and target repo.
- Consider adding `read` as a fallback tool alongside `lsp_symbols`.
- Or rewrite the tool restriction prefix for `13_lsp` to give more explicit guidance on how to use LSP output to navigate to the target file.
- Run `13_lsp` in isolation after the fix and verify `made_changes=True`.

---

## 3. Fix Serena and Semble — latency and correctness

**Problem**: `16_serena_only` and `20_serena_semble` show `tool_correctness_score=0.0` (judge: no prescribed tools used — agent used `read_file` instead of serena tools). `17_semble_only` and `20_serena_semble` log `ValueError: Could not find expected embedding model` during semble init.

**Actions**:
- Verify serena MCP subprocess starts correctly inside each worktree and that the agent actually calls serena tools (not the plain `read` tool).
- Fix the serena project config injection (`_inject_serena_project_config`) so it works correctly inside worktrees.
- For semble: verify the fastembed ONNX model is pre-downloaded to a stable cache path (`/tmp/fastembed_cache/`) before benchmark starts; add a preflight check that confirms the model is available.
- Add explicit warmup steps in `PreflightChecker` for both MCP servers: start, ping, verify tool list, shut down.
- Measure and log MCP server startup time separately from agent execution time.

---

## 4. Expand evaluation metrics

**Current**: 3 judge scores (task_solved, tool_correctness, context_quality) + eval_score.

**Additions needed**:

### 4a. Four additional judge reasoning scores
- `correctness_score` — Is the written code syntactically and semantically correct? (0.0–1.0)
- `minimality_score` — Did the agent make only the required changes without touching unrelated code? (0.0–1.0)
- `pattern_adherence_score` — Did the agent follow the existing code patterns in the repo? (0.0–1.0)
- `tool_sequence_score` — Did the agent use tools in a logical, non-redundant order? (0.0–1.0)

### 4b. Two RAG-specific metrics
- `retrieval_precision` — Of all files/symbols the agent read, what fraction was actually relevant to the task? (relevant_reads / total_reads)
- `retrieval_recall` — Of all files/symbols needed to solve the task, what fraction did the agent actually read? (relevant_reads / required_reads) — requires a ground-truth `required_files` list per benchmark config.

**Implementation**: Extend `LLMJudge.evaluate()` and the `JudgeReport` model. Add `required_files` field to benchmark config YAML.

---

## 5. Unified setup pipeline (preflight)

**Problem**: The setup process is fragmented across `run_benchmark_wsl.sh`, `scripts/setup_benchmark.sh`, multiple install scripts, and manual steps. A new contributor cannot reproduce the environment without reading all of them.

**Goal**: Single entry point that handles everything end-to-end.

**Pipeline stages** (one script or `main.py --setup`):
1. **Platform detection**: WSL2/Linux/macOS/Windows.
2. **System tool checks**: uv, node, rg, ugrep, git, ast-grep, serena, uvx. Install missing ones.
3. **Python venv**: rebuild `.venv-wsl` (or `.venv`) with `UV_LINK_MODE=copy` on WSL/NTFS. Verify all packages installed.
4. **Agno initialization**: verify Agno imports, register all tools, confirm each tool is visible. Log: `[TOOL_NAME]: OK / MISSING`.
5. **MCP verification**: start Serena and Semble as MCP subprocess, confirm tool counts (≥1 each), shut down.
6. **Target repo preparation**: `uv sync --extra dev` in target repo, confirm baseline test count > 0.
7. **Dry-run**: run all 20 configs with `--dry-run`, confirm all 20 return `Success=True`.
8. **Metrics sanity check**: verify that judge scores, reasoning fields, and cost fields are correctly populated in the dry-run output JSONs.

All stages must produce a clear PASS/FAIL line. A failed stage aborts with a helpful error message.

---

## 6. Update README and AGENTS.md for zero-friction onboarding

**Problem**: A new contributor cloning the repo cannot tell what to do first. The current README and AGENTS.md describe architecture but not the operational workflow.

**Goal**: Clone → run one command → benchmark runs.

**Changes needed**:
- `README.md`: add a "Quick Start" section at the top. Three steps: (1) clone, (2) run preflight (`python main.py --setup`), (3) run benchmark (`python main.py`). Include expected output for each step.
- `AGENTS.md`: add a "For AI Agents" section describing the two-phase protocol: (1) always run preflight first, (2) then run benchmark. Explain what each phase does and what success looks like.
- Add a `CONTRIBUTING.md` (or section in README) describing how to add a new benchmark config.
- Verify all file paths and commands in existing docs are still accurate after the infrastructure rebuild.

---

## 7. Post-benchmark HTML dashboard

**Problem**: Results are scattered across 20 `metrics.json` files. Analysis requires manual reading or ad-hoc scripts.

**Goal**: Third pipeline (`python main.py --dashboard` or `python main.py --report`) that:
1. Reads all `results/run_TIMESTAMP_*/metrics.json` files.
2. Builds a single-page HTML dashboard with:
   - Summary card: total runs, success rate, total cost, date.
   - Sortable table: all configs × all metrics.
   - Bar charts: tokens per config, success/token per config, cost per config.
   - Judge scores radar chart per config.
   - Trend view if multiple runs exist (success rate over time).
3. Writes `results/dashboard_TIMESTAMP.html`.
4. Starts a local HTTP server on `localhost:8080` and opens the browser.
5. Prints the URL to stdout.

**Tech**: Single-file HTML with embedded Chart.js (CDN) and inline JSON data. No external server dependencies.

---

## 8. Verify target codebase preparation in preflight

**Problem**: The current `_setup_target_repo` runs `uv sync --extra dev` and spot-checks syntax, but does not verify that the actual benchmark task is solvable in principle (e.g., target file exists, baseline tests pass, no pre-existing failures in the test file being modified).

**Actions**:
- Add a preflight check that confirms the target file named in `benchmark.target_file` (if specified in config YAML) actually exists in the target repo.
- Run `pytest` on the specific test file being modified and confirm it passes before benchmark starts.
- Log the baseline test count for the specific test file (not just the whole suite).
- If `baseline_pass_count == 0` for the specific file, raise a clear error with remediation steps.
- Add `target_file` and `target_test` fields to `BenchmarkMeta` in `benchmark_configs.yaml`.

---

## Priority order (suggested)

| Priority | Item | Reason |
|---|---|---|
| P0 | #1 env_error | Blocks real test validation for all 19 passing configs |
| P0 | #5 unified pipeline | Required for reproducibility |
| P1 | #2 lsp fix | Only hard failure |
| P1 | #4 metrics expansion | Core benchmark value |
| P1 | #8 target repo preflight | Data integrity |
| P2 | #3 serena/semble | Quality improvement |
| P2 | #6 README/AGENTS | Onboarding |
| P3 | #7 dashboard | Nice to have |
