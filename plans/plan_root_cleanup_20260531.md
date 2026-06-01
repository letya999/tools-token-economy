# Plan: Root Cleanup + README/GEMINI.md Update

Date: 2026-05-31
Status: Pending

---

## Summary

Clean up the project root: remove debug/temp/stale files from git, move docs to proper locations,
delete untracked artifacts locally, and update README.md + GEMINI.md content.

---

## Step 1: Git remove (git rm) — tracked files to delete

Run these commands from the project root (C:\Users\User\a_projects\tools_token_economy):

```bash
git rm debug_agno_mcp.py debug_mcp.py
git rm test_agno_agent.py test_agno_connect.py test_agno_debug_internal.py
git rm test_agno_discovery.py test_agno_functions.py test_direct_handover.py
git rm _gen_dashboard.py
git rm BACKLOG.md
git rm run_benchmark_wsl.sh
```

Reason:
- `debug_*.py` and `test_agno_*.py` (8 files): one-off Agno/MCP debug scripts, learnings already
  incorporated into `scripts/verify/verify_serena_mcp.py`
- `_gen_dashboard.py`: duplicates `python main.py --dashboard`, not documented anywhere
- `BACKLOG.md`: stale task list from 2026-05-27, most items already implemented
- `run_benchmark_wsl.sh`: superseded by `scripts/run_wsl.sh` (no hardcoded paths, auto-venv creation)

---

## Step 2: Git move tracked docs to docs/

```bash
mkdir -p docs/archive
git mv BENCHMARK_SETUP.md docs/BENCHMARK_SETUP.md
git mv BENCHMARK_RUN_20260526_RESULTS.md docs/archive/BENCHMARK_RUN_20260526_RESULTS.md
```

Reason:
- `BENCHMARK_SETUP.md`: architecture doc for scripts/ pipeline, belongs in docs/
- `BENCHMARK_RUN_20260526_RESULTS.md`: post-mortem of an INVALID run, historical reference

---

## Step 3: Delete untracked local artifacts (not in git)

Delete these directories and files (they are untracked and gitignored already):

Directories to delete:
- `build/`  (Python bdist artifacts)
- `.eval_venv/`  (old Windows-FS venv, caused the 2026-05-26 benchmark failure)
- `.temp_venv/`  (clearly temporary)
- `results_dry/`
- `results_dry_run/`
- `results_dry_run_agno_v2/`
- `results_real/`
- `results_verify/`

Log files to delete (all *.log in root):
- `benchmark_latest.log`
- `benchmark_run_20260529.log`
- `benchmark_run_20260529b.log`
- `benchmark_run_20260529c.log`
- `benchmark_run_20260529_final.log`
- `benchmark_run_20260530_002121.log`
- `benchmark_wsl_run.log`
- `run_benchmark_wsl.log`
- `result.log`
- `serena_test.log`

Use PowerShell Remove-Item -Recurse -Force for directories, Remove-Item for files.

---

## Step 4: Update GEMINI.md

File: `GEMINI.md`

Current content is outdated — references Gemini 2.5 Flash rate limits (10 rpm) but project
now runs on gpt-4.1-mini.

Replace the file with this content:

```markdown
# Project Instructions: Tools Token Economy Benchmark

This project is a research framework for evaluating the effectiveness of tools and navigation strategies for coding agents.

## Foundation
Foundational instructions and engineering standards for this repository are defined in:
- **[AGENTS.md](./AGENTS.md)**: Core mandates, architecture, and workflow instructions.

## Key Constraints
- **Model**: gpt-4.1-mini (default), configurable in `configs/provider.yaml`
- **Sequential Only**: No parallel agent execution during benchmark runs.
- **Environment**: WSL2 Ubuntu — use `bash scripts/run_wsl.sh` to launch.
```

---

## Step 5: Update README.md

File: `README.md`

### Changes required:

#### 5a. Add run metadata above the results table

After the line "20 of 21 configs passed (95%). Key findings:", add:

```
> **Run metadata:** n=1 · model=gpt-4.1-mini · task=medium · 2026-05-30
> Results below show selected configs sorted by SPT. Full interactive table in the dashboard.
```

#### 5b. Relabel the archetype descriptions in "Tool configs" section

In the table under "## Tool configs", change the Philosophy column for cursor/claude/gemini/codex rows to make clear these are approximations, not benchmarks of the actual products:

- `cursor` row: change Philosophy from "Repo map + RAG for broad context" to "Repo map + RAG for broad context (cursor-inspired archetype)"
- `claude` row: change "Glob + ripgrep for surgical search" to "Glob + ripgrep for surgical search (claude-inspired archetype)"
- `gemini` row: change "Read all + rg (context-first)" to "Read all + rg (context-first, gemini-inspired archetype)"
- `codex` row: change "Grep + read (classic Unix)" to "Grep + read (classic Unix, codex-inspired archetype)"

Add a note after the table:
```
> Archetype names reflect the tool *philosophy* associated with each coding assistant, not a benchmark of the product itself. Actual Cursor, Claude Code, Gemini, and Codex behavior differs.
```

#### 5c. Soften the "Bottom line" statement

Change:
```
**Bottom line:** Targeted search tools (`git_grep`, `rg`, `grep`) massively outperform bulk-read strategies. The Claude Code-like toolset (glob+rg) achieves 58x better token efficiency than read\_all at 28x lower cost.
```

To:
```
**Bottom line:** Targeted search tools (`git_grep`, `rg`, `grep`) use significantly fewer tokens than bulk-read strategies. In this single run, `git_grep` achieved the best SPT score (12K tokens vs 682K for `read_all`). Multi-run aggregation needed for statistical confidence.
```

#### 5d. Fix the 03_gemini_like footnote

Change:
```
> `03_gemini_like` (read\_all + repo\_map) failed — context explosion from reading the entire repo exceeded the model's usable window.
```

To:
```
> `03_gemini_like` (read\_all + repo\_map) used 682K tokens — agent entered a read loop. Excluded from table due to extreme token cost distorting scale.
```

#### 5e. Update Quick start section — replace outdated WSL command

In "### 3. Setup" section, change:
```bash
wsl bash -c "cd /mnt/c/path/to/tools-token-economy && uv run python main.py --setup"
```
To:
```bash
wsl bash scripts/run_wsl.sh --dry-run
```

In "### 4. Run the benchmark" section, change:
```bash
wsl bash -c "cd /mnt/c/path/to/tools-token-economy && uv run python main.py"
```
To:
```bash
wsl bash scripts/run_wsl.sh
```

---

## Step 6: Commit

```bash
git add docs/BENCHMARK_SETUP.md docs/archive/BENCHMARK_RUN_20260526_RESULTS.md
git add GEMINI.md README.md
git commit -m "chore: clean up root, move docs, update README and GEMINI.md"
```

---

## Notes

- Do NOT delete `.venv-wsl/` — it is the active WSL virtual environment
- Do NOT touch `plans/` directory contents (gitignored)
- Do NOT modify anything in `src/`, `configs/`, `tests/`, `scripts/`
- The `results/` directory itself should remain (gitignored, but holds current run data)
