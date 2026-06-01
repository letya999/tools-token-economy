# Plan: Statistical Matrix Overhaul (internal + external validity)

Date: 2026-05-31
Project: tools_token_economy
Author intent (from user): Fix the audit findings, then make the benchmark capable of a
multi-task × multi-model matrix that yields BOTH internally significant (per task, 5-7 runs,
bootstrap CI) AND externally significant (across ~10 Python tasks on ONE codebase, Friedman +
Nemenyi) conclusions about WHICH TOOLS save the most tokens while correctly solving tasks.
A single cheap run (1 task × 1 model × 1 config-set × 1 run) MUST remain possible and must not
blow the budget. Budget and cycle limits MUST work for both single and matrix runs.

This benchmark ranks TOOLS, not models/tasks. Model and task are held constant within a cell;
tools vary. External validity comes from repeating across many tasks (and confirming stability
across models).

## EXECUTION RULES FOR IMPLEMENTER (Gemini)
- Work PHASE BY PHASE. Each phase has an ACCEPTANCE GATE. Do not start a later phase until the
  prior gate passes.
- After each phase run: `bash scripts/run_wsl.sh` is NOT required for unit tests; use
  `uv run pytest tests/ -q` (in WSL native fs; set `UV_LINK_MODE=copy` if uv runs on /mnt/c).
  Report pass/fail counts.
- Do NOT run the full PAID benchmark. Only `--dry-run`, `--estimate`, and unit tests. The user
  runs paid matrix runs manually after review.
- Target repo for tasks lives at: C:\Users\User\a_projects\process_metrics_platform_v2
  (WSL: /c/Users/User/a_projects/process_metrics_platform_v2 — NOT /mnt/c). It is a Python +
  Polars repo. Inspect it to author repo-specific, memory-proof tasks.
- Python style: type hints on all funcs, Google docstrings, snake_case, no `any`, no emojis,
  English only. No AI attribution in code/commits. Single source of config truth in configs/.
- Do NOT delete existing tasks (aging_stale.yaml, easy/medium/hard). Keep backward compat:
  `python main.py` with no new flags must behave exactly as today.

================================================================================
## CONTEXT: verified current state (do not re-discover, just trust + verify)
================================================================================
- `--runs` default = 5 (main.py:162). Multi-run loop exists (benchmark.py:485-537).
- Per-run seed offset works: benchmark.py:516 `seed = orig_seed + rep`.
- Stats machinery EXISTS and is correct (src/features/stats.py: coefficient_of_variation,
  bootstrap_ci, ci_overlap, run_validity_status with STATUS_OK/LOW_CONFIDENCE/
  INSUFFICIENT_DATA/UNSTABLE). aggregate_session (src/features/multi_run.py) already filters
  invalid runs (parametric_success / agent_runaway / not telemetry_ok), computes per-config
  n_valid, _validity_status, _spt_ci_lo/hi, _spt_cv, _suggested_additional_runs.
- BUG #1 (DEAD WIRING): `ci_overlap` is defined but USED NOWHERE. Significance-aware ranking
  (Phase 4.5 of prior plan) was never implemented.
- BUG #2 (DEAD WIRING): `_validity_status` / `_spt_ci_*` are computed but only printed to the
  terminal (main.py:286). Dashboard (dashboard_builder.py) and Streamlit rank purely by
  `composite_score` point estimate (dashboard_builder.py:234) — no tie-bands, no not-ranked
  section. CSV export carries no CI/status/n_valid columns.
- BUG #3 (METRIC INCONSISTENCY): `net_spt` (agno_runner.py:464/506) is gated by BINARY success,
  while `success_per_token` (models.py:197) uses GRADED task_solved_score. Two "headline"
  efficiency metrics disagree on the numerator.
- BUG #4 (TOO BRUTAL): compute_eval_composite (src/core/scoring.py:51-53) returns 0.0 if ANY of
  the 7 judge dimensions is exactly 0. A config that legitimately scores 0 on one axis (e.g.
  bash_only on tool_correctness) gets its whole eval_score annihilated.
- BUG #5 (UNPROVEN): aging_stale memory-proofness is auto-detected via parametric_success but
  never demonstrated on a real run.
- LIMIT: only ONE task, ONE agent model. No task-suite, no model-sweep, no cross-task
  (external) aggregation. CostGuard (cost_guard.py) is per-suite only; limits are hardcoded in
  orchestrator __init__ (max_suite_usd=8.0, max_config_usd=0.40, max_tokens_per_config=600_000)
  and NOT exposed via CLI/config; there is no matrix-level budget cap and no cost estimator.

================================================================================
## PHASE 1 — Fix the metric/scoring bugs (cheap, no API)
================================================================================

### 1.1 Reconcile net_spt with success_per_token  (BUG #3)
MODIFY: src/features/agent_integration/agno_runner.py (both sites ~464 and ~506) AND/OR move
the computation into src/core/models.py as a computed_field for single-source-of-truth.
- Decide ONE numerator: graded `task_solved_score` with fallback to 1.0 when task_solved is 0
  but success is True (mirror the success_per_token logic in models.py:201-205).
- net_spt = (base_score * 1000.0) / reasoning_tokens, where
  reasoning_tokens = max(total_tokens - schema_overhead_tokens, 1).
- PREFER: implement net_spt as a `@computed_field` on RunMetrics so it always derives from
  stored fields (task_solved_score, total_tokens, schema_overhead_tokens, success), and REMOVE
  the manual net_spt assignment in agno_runner (keep schema_overhead_tokens stored). This kills
  the binary/graded split permanently. Keep success_per_token as-is (per-1M) but document that
  net_spt is the SCHEMA-FAIR primary efficiency metric (per-1K reasoning tokens).
- Document in a comment: net_spt is the HEADLINE token-economy metric (schema-overhead-adjusted,
  graded), success_per_token is the raw secondary metric.

### 1.2 Soften the geometric-mean hard-zero  (BUG #4)
MODIFY: src/core/scoring.py compute_eval_composite.
- Keep `success` as a HARD gate (return 0.0 if not success) — that is correct.
- Replace the "any dimension == 0 -> 0.0" behavior with an epsilon FLOOR per dimension:
  `val = max(float(judge_scores.get(key, 0.0)), EPS)` with module constant `EPS = 0.01`.
  This way a single weak axis heavily penalizes (geometric mean) but does not annihilate.
- Add docstring rationale + a module constant. Update/extend the existing scoring unit test.

### 1.3 ACCEPTANCE GATE
- Unit test: a config with task_solved=0.6, others ~0.5 -> eval_score in (0, 0.7), NOT 0, NOT 1.
- Unit test: success=False -> eval_score == 0.0 (hard gate preserved).
- Unit test: net_spt for success with task_solved=0.5 equals
  (0.5*1000)/max(total-schema,1); and net_spt==0 when success False.
- `uv run pytest tests/ -q` green.

================================================================================
## PHASE 2 — Significance-aware ranking + honest surfacing  (BUG #1, #2)
================================================================================

### 2.1 Significance-aware ranking helper
CREATE FILE: src/features/significance.py
- `def rank_with_tiebands(configs: list[dict], metric_key: str, ci_key_lo: str, ci_key_hi: str)
   -> list[dict]`: sort configs by point estimate (median of metric_key) descending, then assign
   a `tie_band` integer: walk the sorted list; configs whose CIs overlap (use stats.ci_overlap)
   with the current band leader share the band; otherwise start a new band. Output each config
   annotated with `rank`, `tie_band`, and `rank_note` (e.g. "tied with #2-#4").
- `def partition_by_status(configs) -> tuple[ranked, not_ranked]`: not_ranked = configs whose
  `_validity_status` in {INSUFFICIENT_DATA, UNSTABLE}. ranked = the rest.
- Pure functions, fully unit-testable, no I/O.

### 2.2 Wire into dashboard
MODIFY: src/features/dashboard_builder.py
- The session/multi-run path must consume aggregate_session output (which already has
  _validity_status, _spt_ci_lo/hi, n_valid). Build the Winners table via
  significance.rank_with_tiebands on net_spt (primary) with the SPT CI; show columns:
  rank, tie_band, config, pass, eval_composite, net_spt (median), SPT 90% CI [lo, hi], tokens,
  status, n_valid/n_total.
- Add a separate "Not Ranked (insufficient data / unstable)" table for partition_by_status
  output, with the reason and `_suggested_additional_runs`.
- For the single-run (n_runs==1) path: keep current behavior but add a visible banner
  "SINGLE RUN — no statistical significance; run with --runs >= 5 for CIs." Do not fabricate CIs.

### 2.3 Wire into Streamlit
MODIFY: streamlit_app.py
- Same tie-band ranking + not-ranked section.
- Add a proper CSV export (st.download_button) of the AGGREGATED per-config table including:
  config_id, status, n_valid, n_total, net_spt_median, net_spt_p25, net_spt_p75,
  spt_ci_lo, spt_ci_hi, cv, eval_composite_median, total_tokens_median, cost_median.
  This export is the scientifically honest artifact (replaces the flat single-run dump).

### 2.4 ACCEPTANCE GATE
- Unit tests for rank_with_tiebands (overlapping CIs share a band; disjoint CIs separate) and
  partition_by_status.
- `uv run python main.py --dry-run --runs 1` builds a dashboard without error and shows the
  SINGLE RUN banner.
- `uv run pytest tests/ -q` green.

================================================================================
## PHASE 3 — Task SETS on one codebase (the external-validity substrate)
================================================================================

Goal: make it trivial to define, in the configs folder, a SUITE of ~10 Python tasks on the
SAME codebase, each memory-proof and deterministic, spanning different retrieval archetypes so
that "which tool wins" is not confounded by a single task's character.

### 3.1 Task-suite manifest schema
CREATE FILE: configs/task_suites/python_core_v1.yaml
```yaml
name: "python_core_v1"
description: "10 repo-specific Polars/pandas tasks on process_metrics_platform_v2 spanning retrieval archetypes."
codebase: "configs/codebase.yaml"   # ONE codebase for the whole suite
tasks:
  - file: "configs/tasks/aging_stale.yaml"        # structural / multi-return
    category: "structural"
  - file: "configs/tasks/<task_02>.yaml"
    category: "string_search"
  # ... 10 entries total, categories drawn from:
  # string_search, structural, cross_file, refactor, signature_change,
  # constant_extraction, branch_completion, test_addition, schema_change, bugfix
```
- Categories matter: external validity requires task DIVERSITY. Aim for >=6 distinct categories
  across the 10 tasks so no single retrieval style dominates.

### 3.2 Author ~10 repo-specific tasks
CREATE FILES: configs/tasks/<task_NN_name>.yaml  (9 new + reuse aging_stale = 10)
- INSPECT the target repo at C:\Users\User\a_projects\process_metrics_platform_v2 first
  (pipelines/calculations/*.py, tests/unit/*). Build tasks ONLY around real functions/files
  that exist there. Each task MUST:
  - Be solvable by a deterministic `test_cmd` (pytest on a specific test file).
  - Be MEMORY-PROOF: depend on bespoke repo logic (commitment points, cross-project leakage,
    column schemas) so it is NOT answerable from model training memory. Validation: a config
    with NO retrieval tools (bash_only) must NOT be able to solve it with files_read<2 — this is
    auto-flagged by the existing parametric_success detector; the suite is valid only if real
    runs do not show parametric_success for the no-tool config.
  - Follow the SAME yaml schema as aging_stale.yaml (difficulty, name, description, test_cmd,
    timeout_sec, target_file, required_files, success_criteria).
  - Vary the retrieval archetype per the category (e.g. a pure string-rename task vs a
    cross-file signature change vs an empty-branch schema completion).
- Add a short authoring guide: docs/TASK_AUTHORING.md (how to add a task + suite, the
  memory-proof rule, the deterministic-test rule, the category taxonomy).

### 3.3 Loader for suites
MODIFY: src/core/config_loader.py
- `def load_task_suite(path: str) -> list[TaskConfig]`: parse the manifest, resolve each task
  file via existing load_task_config, attach `.category` (add `category: str = ""` to TaskConfig
  in models.py). Validate every referenced file exists; raise a clear error listing missing ones.

### 3.4 ACCEPTANCE GATE
- Unit test: load_task_suite returns N TaskConfig with categories; missing-file -> clear error.
- `uv run python main.py --dry-run --task-suite configs/task_suites/python_core_v1.yaml --runs 1`
  loads all tasks and runs the dry pipeline for each without error.
- `uv run pytest tests/ -q` green.

================================================================================
## PHASE 4 — Model sweep (hold task constant, vary model — for tool-stability check)
================================================================================

### 4.1 Model-sweep manifest
CREATE FILE: configs/model_sweep.yaml
```yaml
# Each entry is an agent-model under test. Judge stays fixed (provider.yaml judge block).
models:
  - provider: "openai"      ; model: "gpt-4.1-mini"   ; api_key_env: "OPENAI_API_KEY"
  - provider: "openai"      ; model: "gpt-4.1-nano"   ; api_key_env: "OPENAI_API_KEY"
  - provider: "anthropic"   ; model: "claude-haiku-4-5" ; api_key_env: "ANTHROPIC_API_KEY"
  - provider: "google"      ; model: "gemini-2.5-flash"; api_key_env: "GOOGLE_API_KEY"
```
(Use proper YAML; the inline `;` above is shorthand. 4 cheap models. Reuse provider_factory.)
MODIFY: src/core/config_loader.py — `def load_model_sweep(path) -> list[ProviderConfig]`,
inheriting temperature/seed/max_steps and the judge block from configs/provider.yaml so only the
agent model varies.

### 4.2 ACCEPTANCE GATE
- Unit test: load_model_sweep returns 4 ProviderConfig with the shared judge block.
- `uv run pytest tests/ -q` green. No live calls.

================================================================================
## PHASE 5 — Matrix orchestrator (models × tasks × configs × runs)
================================================================================

### 5.1 Matrix runner
CREATE FILE: src/orchestrator/matrix.py
- `class MatrixOrchestrator`: given list[ProviderConfig] models, list[TaskConfig] tasks, the
  tools_configs, codebase, weights, results_dir, n_runs, budget config, dry_run.
- For each (model, task): construct a BenchmarkOrchestrator and call run_suite with a session id
  labelled `session_{model_slug}_{task_slug}_{ts}`. Persist a matrix manifest
  results/matrix_{ts}_manifest.json listing every (model, task, session_id, status).
- Order: iterate model OUTER, task INNER (so the user can stop after model 1 and still have a
  complete per-model picture). Each cell is independent and resumable.
- Respect a MATRIX-level budget cap (Phase 6) across all cells; stop cleanly when exceeded and
  record which cells were skipped.
- Single-run path is UNAFFECTED: MatrixOrchestrator is only used when --matrix / --task-suite /
  --models is requested. Plain `python main.py` keeps using BenchmarkOrchestrator directly.

### 5.2 main.py wiring
MODIFY: main.py
- New flags:
  - `--task-suite PATH` (run all tasks in a suite on the configured/sole model)
  - `--models PATH` (model-sweep manifest)
  - `--matrix` (require both --task-suite and --models; full matrix)
  - `--estimate` (print matrix size + projected cost/tokens, then EXIT without spending)
  - `--yes` (skip the interactive confirmation gate for paid matrix runs)
- Dispatch logic:
  - If --matrix or (--task-suite and --models): build MatrixOrchestrator.
  - elif --task-suite only: loop tasks on the single provider.yaml model (still via matrix with
    one model) OR a thin task-loop — keep it simple: MatrixOrchestrator with models=[provider.yaml].
  - elif --models only: loop models on the single configured task.
  - else: EXACT current single-orchestrator behavior (no regression).
- Keep `--runs` default 5; document `--runs 1` for the cheap smoke run.

### 5.3 ACCEPTANCE GATE
- `uv run python main.py --dry-run --matrix --task-suite configs/task_suites/python_core_v1.yaml
   --models configs/model_sweep.yaml --runs 1` completes the dry matrix and writes a manifest.
- `uv run python main.py --dry-run --runs 1` still works exactly as before (regression).
- `uv run pytest tests/ -q` green.

================================================================================
## PHASE 6 — Budget & cycle guards for single AND matrix  (the "no budget debri" rule)
================================================================================

### 6.1 Expose budget via config + CLI
CREATE FILE: configs/budget.yaml
```yaml
max_config_usd: 0.40          # per single config run
max_tokens_per_config: 600000 # per single config run (cycle/token runaway guard)
max_session_usd: 8.0          # one (model,task) suite = all configs x n_runs
max_matrix_usd: 50.0          # hard cap across the whole models x tasks matrix
```
MODIFY: src/core/config_loader.py — `def load_budget_config(path) -> dict` with these defaults.
MODIFY: main.py — flags `--max-config-usd`, `--max-tokens-per-config`, `--max-session-usd`,
  `--max-matrix-usd` override the file. Pass through to orchestrators.
MODIFY: src/orchestrator/benchmark.py __init__ — read these instead of hardcoded literals
  (keep current values as DEFAULTS so existing behavior is identical when nothing is passed).

### 6.2 Matrix-level cost guard + estimator
MODIFY: src/features/cost_guard.py
- Add `class MatrixCostGuard` (or extend CostGuard) tracking cumulative spend across sessions
  against max_matrix_usd; `check_matrix_budget()` raises before starting a new cell when the
  remaining budget can't cover an estimated cell cost.
- Add `def estimate_matrix_cost(n_models, n_tasks, n_configs, n_runs, avg_usd_per_run=0.02,
  avg_tokens_per_run=120000) -> dict`: returns projected runs, USD, tokens. (avg defaults from
  observed CSV: ~$0.02 / ~120K tokens per config-run; make them overridable.)
- main.py --estimate prints this table and the configured caps, then exits. For an actual paid
  matrix run (not --dry-run, not --yes), print the estimate and require a y/N confirmation.

### 6.3 Cycle/iteration limits for both modes
VERIFY + DOCUMENT (no behavior change unless broken): max_steps / max_iterations
(provider.yaml + ProviderConfig) are applied PER RUN identically in single and matrix paths
(they already pass through _run_single_config). agent_runaway already trips on token_exceeded /
tool_errors>10 / agent_cycles>40. Confirm these fire in matrix cells too (they will, since each
cell reuses BenchmarkOrchestrator). Add a unit test asserting agent_runaway flag logic and that
token_exceeded honors the configured max_tokens_per_config.

### 6.4 ACCEPTANCE GATE
- `uv run python main.py --estimate --matrix --task-suite configs/task_suites/python_core_v1.yaml
   --models configs/model_sweep.yaml --runs 6` prints projected runs/USD/tokens and the caps,
   then exits 0 WITHOUT any API call.
- Unit tests: estimate_matrix_cost math; MatrixCostGuard stops at cap; budget overrides parse.
- Single run `--runs 1` projected cost stays small (one model, one task, configs x 1).
- `uv run pytest tests/ -q` green.

================================================================================
## PHASE 7 — External validity: cross-task aggregation (Friedman + Nemenyi)
================================================================================

This is the scientific core of "across 10 tasks, tool X is consistently better."

### 7.1 Cross-task statistics module
CREATE FILE: src/features/cross_task.py
- Input: for a FIXED model, the per-(task) aggregate_session outputs (one per task in the suite),
  each giving per-config median net_spt (and eval_composite, total_tokens).
- Build a matrix M[config][task] = median net_spt of that config on that task (use only configs
  whose per-task status is OK or LOW_CONFIDENCE; mark missing/excluded cells).
- Implement (pure python + numpy/scipy if available; if scipy not a dep, implement Friedman and
  Nemenyi by hand — both are closed-form):
  - `average_ranks(M) -> dict[config, float]`: per task rank configs (1=best net_spt), average
    each config's ranks across tasks.
  - `friedman_test(M) -> (stat, p_value, k, n)`: Friedman chi-square across configs over tasks.
  - `nemenyi_critical_difference(k, n, alpha=0.05) -> float`: CD = q_alpha * sqrt(k(k+1)/(6n)).
    Include the standard q_alpha table for alpha=0.05 (Studentized range / sqrt(2)).
  - `cross_task_report(M) -> dict`: returns average ranks, Friedman stat/p, CD, and groups of
    configs that are statistically indistinguishable (rank difference < CD), plus a
    "consistent_winners" list (lowest average rank, separated by > CD from the field).
  - `win_rate(M) -> dict[config, float]`: fraction of tasks where the config is in the top tier.
- Reference: Demšar (2006), "Statistical Comparisons of Classifiers over Multiple Data Sets".
  Cite in the module docstring. (Implementer may use context7/web to confirm the q_alpha table
  and the CD formula. DO confirm the formula before coding.)

### 7.2 Cross-model stability
- `def rank_stability(per_model_ranks: dict[model, dict[config, float]]) -> dict`: Spearman/
  Kendall correlation of the average-rank vectors between models, plus a note whether the
  top-tier (within-CD) set is the same across models. This separates "tool effect" from
  "model effect": a tool that wins across tasks AND models is a robust result.

### 7.3 Surfacing
MODIFY: streamlit_app.py and src/features/dashboard_builder.py
- Add a "Cross-Task (External Validity)" panel per model: average-rank table, Friedman p-value,
  a critical-difference summary (which configs are indistinguishable), consistent winners, and
  per-config win-rate across tasks.
- Add a "Cross-Model Stability" panel: rank-correlation matrix + whether the winner set holds.
- CSV export for the cross-task table (config, avg_rank, win_rate, friedman_p, cd, tier).

### 7.4 ACCEPTANCE GATE
- Unit tests on cross_task with a SYNTHETIC matrix where one config dominates every task
  (Friedman significant, that config is the sole consistent winner) and one where all configs
  are equal (Friedman not significant, all in one CD group). Verify CD math against a hand
  example.
- `uv run pytest tests/ -q` green.

================================================================================
## PHASE 8 — Protocol docs + README honesty
================================================================================
MODIFY/CREATE:
- docs/BENCHMARK_PROTOCOL.md (NEW): the canonical run protocol —
  1) cheap smoke: `python main.py --runs 1` (one task, one model, all configs, ~$ small).
  2) internal significance per cell: `--runs 5..7` on one task/model -> per-config CI + status.
  3) per-task sweep: `--task-suite ... --runs 6` on one model -> internal CI per task, then
     cross-task Friedman/Nemenyi -> external validity for that model.
  4) full matrix: `--matrix --task-suite ... --models ... --runs 6` -> cross-task per model +
     cross-model stability. Always `--estimate` first.
  Document the budget caps and how to raise them; document that overlapping CIs = indistinguishable.
- docs/TASK_AUTHORING.md (from Phase 3.2).
- README.md / README_RU.md: replace any "Nx better" single-run claims with the protocol; state
  scope honestly: "tool token-economy on Python codebases, validated across N tasks / M models;
  configs with overlapping CIs are statistically tied." Leave numeric tables as TODO for the
  user's real run.
- Update AGENTS.md command quick-reference with the new flags.

### ACCEPTANCE GATE
- `uv run python main.py --help` shows all new flags with clear help text.
- `uv run pytest tests/ -q` green. Provide the final pass/fail count.

================================================================================
## FILES SUMMARY
================================================================================
CREATE:
- configs/task_suites/python_core_v1.yaml
- configs/tasks/<task_02..task_10>.yaml  (9 new, repo-specific, memory-proof)
- configs/model_sweep.yaml
- configs/budget.yaml
- src/features/significance.py
- src/orchestrator/matrix.py
- src/features/cross_task.py
- docs/BENCHMARK_PROTOCOL.md
- docs/TASK_AUTHORING.md
- tests for: significance, cross_task, matrix (dry), budget/estimate, scoring epsilon, net_spt,
  loaders (suite/sweep/budget)

MODIFY:
- src/core/scoring.py (epsilon floor)
- src/core/models.py (net_spt computed_field; TaskConfig.category; budget plumbing if needed)
- src/features/agent_integration/agno_runner.py (drop manual net_spt; keep schema_overhead)
- src/core/config_loader.py (load_task_suite, load_model_sweep, load_budget_config)
- src/features/cost_guard.py (MatrixCostGuard + estimate_matrix_cost; config-driven limits)
- src/orchestrator/benchmark.py (config-driven budget; session labelling pass-through)
- src/features/dashboard_builder.py (tie-band ranking, status, CI, single-run banner, cross-task panel)
- streamlit_app.py (tie-band ranking, not-ranked section, honest CSV export, cross-task + stability panels)
- main.py (new flags, matrix dispatch, estimate/confirm gate, budget overrides)
- README.md, README_RU.md, AGENTS.md, configs/provider.yaml (comments)

## OUT OF SCOPE / DO NOT DO
- Do NOT run paid benchmarks (only --dry-run / --estimate / unit tests).
- Do NOT change the target repo (process_metrics_platform_v2) — the agent edits it at runtime in
  an isolated worktree.
- Do NOT break `python main.py` default single-run behavior.
- Do NOT commit secrets; all keys via api_key_env.
- Do NOT add scipy as a hard dependency unless already present; implement Friedman/Nemenyi by
  hand if scipy is absent (guard the import).

## HARD ACCEPTANCE (whole plan)
1. `uv run pytest tests/ -q` fully green (report count).
2. `uv run python main.py --dry-run --runs 1` == today's behavior (regression safe).
3. `uv run python main.py --estimate --matrix --task-suite configs/task_suites/python_core_v1.yaml
   --models configs/model_sweep.yaml --runs 6` prints projected runs/USD/tokens + caps, exits 0,
   ZERO API calls.
4. `uv run python main.py --dry-run --matrix --task-suite ... --models ... --runs 1` produces a
   matrix manifest and per-cell dry results.
5. Dashboard/Streamlit show tie-bands (ci_overlap), a not-ranked section, single-run banner, and
   the cross-task + cross-model panels. ci_overlap and _validity_status are now CONSUMED.
