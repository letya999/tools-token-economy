# Plan: Fix Hallucinated Task Paths + Complete Phases 6-8

Date: 2026-05-31
Author intent: The prior Gemini pass (plan_statistical_matrix_overhaul_20260531.md) was
partially implemented. Phases 1-5 landed and 177 tests pass. THREE critical gaps remain:
  A) Several new task YAMLs contain WRONG file paths (hallucinated without reading the repo)
     and broken YAML structure (success_criteria items mixed into required_files lists).
  B) src/features/cross_task.py (Friedman/Nemenyi external validity) — entirely MISSING.
  C) configs/budget.yaml + docs/BENCHMARK_PROTOCOL.md — MISSING.

This plan fixes all three, plus minor cleanup. Do NOT touch Phases 1-5 code (tests pass).

## EXECUTION RULES
- BEFORE editing any task YAML, READ the referenced source file in the target repo to confirm
  it exists and understand what domain-specific change to request.
- Run `uv run pytest tests/ -q` after every phase; report counts. 177 must stay green.
- Do NOT run paid benchmarks — only unit tests and `--dry-run`/`--estimate`.
- Python style: type hints, Google docstrings, snake_case, no `any`.

## VERIFIED GROUND TRUTH: TARGET REPO FILE MAP
Target repo: C:\Users\User\a_projects\process_metrics_platform_v2
WSL path: /mnt/c/Users/User/a_projects/process_metrics_platform_v2

CONFIRMED EXISTS (real paths for tasks):
  Calculation modules:
    pipelines/calculations/aging.py                         (used by aging_stale.yaml — OK)
    pipelines/calculations/backlog_growth.py
    pipelines/calculations/commitment_resolver.py
    pipelines/calculations/cumulative_flow.py               (used by optimize_polars_query.yaml — path OK)
    pipelines/calculations/cycle_time_ext.py
    pipelines/calculations/lead_time.py                     (used by calc_lead_time.yaml — path OK)
    pipelines/calculations/sprint_health.py
    pipelines/calculations/throughput.py
    pipelines/calculations/velocity.py
    pipelines/calculations/waste.py
    pipelines/utils/polars_db.py                            (NOT db/polars_db.py)
    app/services/dagster_client.py                          (NOT pipelines/dagster_client.py)
    app/api/projects.py                                     (NOT app/api/routers/projects.py)
    app/schemas/project.py

  Jira clean modules (NOT pipelines/transformations/jira_clean.py):
    pipelines/assets/jira/clean/issues.py
    pipelines/assets/jira/clean/dimensions.py
    pipelines/assets/jira/clean/sprints.py

  Test files (all confirmed present):
    tests/unit/test_aging.py
    tests/unit/test_backlog_growth.py
    tests/unit/test_commitment_resolver.py
    tests/unit/test_cumulative_flow.py
    tests/unit/test_cycle_time_ext.py
    tests/unit/test_jira_clean.py
    tests/unit/test_lead_time_logic.py
    tests/unit/test_polars_db.py
    tests/unit/test_api_projects_unit.py
    tests/unit/test_sprint_health.py
    tests/unit/test_throughput.py
    tests/unit/test_velocity_logic.py
    tests/unit/test_transformations.py
    tests/unit/test_estimation.py

DOES NOT EXIST (these were hallucinated):
    pipelines/transformations/jira_clean.py    -> WRONG, see pipelines/assets/jira/clean/
    db/estimation.py                           -> WRONG, use pipelines/calculations/estimation.py
    db/polars_db.py                            -> WRONG, use pipelines/utils/polars_db.py
    pipelines/dagster_client.py                -> WRONG, use app/services/dagster_client.py
    app/utils/exporter.py                      -> does not exist
    app/api/routers/projects.py                -> WRONG, use app/api/projects.py

================================================================================
## PHASE A — Fix broken task YAMLs
================================================================================

### STEP A.0: Read before writing
For EACH task YAML you rewrite, you MUST first read the target calculation file to understand
what the code actually does so the task description is grounded in reality.

### A.1 Fix configs/tasks/fix_jira_mapping.yaml
The current required_file `pipelines/transformations/jira_clean.py` does not exist.
- READ: pipelines/assets/jira/clean/issues.py (which handles status assignment, or check
  dimensions.py for the status->category mapping)
- READ: tests/unit/test_jira_clean.py (to understand what the test already verifies)
- Write a valid task based on REAL logic in those files: e.g. if there is a status-mapping
  dict or function, add a new status alias or fix an existing mapping that has wrong output.
  Make the task specific to what the code ACTUALLY does.
- YAML structure (correct):
  ```yaml
  difficulty: medium
  name: "..."
  description: |
    ...
  test_cmd: "uv run --extra dev pytest tests/unit/test_jira_clean.py -q"
  timeout_sec: 600
  target_file: "tests/unit/test_jira_clean.py"
  required_files:
    - "pipelines/assets/jira/clean/issues.py"
    - "tests/unit/test_jira_clean.py"
  success_criteria:
    - "..."
  ```

### A.2 Fix configs/tasks/add_sprint_metric.yaml
YAML STRUCTURE BUG: success_criteria items are mixed into required_files.
Also must READ pipelines/calculations/sprint_health.py first.
- Required files should only be file PATHS, never plain-English strings.
- Correct structure: required_files contains only paths; success_criteria is a separate key.
- Based on what actually exists in sprint_health.py, write a task that adds a computed
  column or new metric derived from existing columns (similar to aging_stale pattern).

### A.3 Fix configs/tasks/add_unit_test_coverage.yaml
`db/estimation.py` does not exist.
- READ: pipelines/calculations/estimation.py (real path)
- READ: tests/unit/test_estimation.py
- Rewrite to use the correct path and design a meaningful task.

### A.4 Fix configs/tasks/change_func_signature.yaml
`db/polars_db.py` does not exist; real path is pipelines/utils/polars_db.py.
- READ: pipelines/utils/polars_db.py
- READ: tests/unit/test_polars_db.py
- Rewrite with correct paths. Make the task concrete (e.g. add/rename a parameter, or add
  a return type hint that is currently missing).

### A.5 Fix configs/tasks/extract_const_pipeline.yaml
`pipelines/dagster_client.py` does not exist.
- READ: app/services/dagster_client.py (real path)
- READ: tests/unit/test_dagster_client.py (if it exists) OR tests/unit/test_definitions.py
- Rewrite with correct paths. Task: extract hardcoded literals into named module constants
  (a pure refactor that is verifiable without touching behaviour — the existing test must pass).

### A.6 Fix configs/tasks/fix_csv_export_bug.yaml
`app/utils/exporter.py` does not exist.
- This file cannot be salvaged without a real exporter. Instead redesign:
  READ: pipelines/utils/transformations.py
  READ: tests/unit/test_transformations.py
  Write a bug-fix task around a real function in transformations.py.

### A.7 Fix configs/tasks/update_api_schema.yaml
`app/api/routers/projects.py` does not exist; real path is app/api/projects.py.
Also READ: app/schemas/project.py and tests/unit/test_api_projects_unit.py.
Rewrite with correct paths. Task: add a new field to the Pydantic schema and expose it in
the API endpoint, verified by the existing unit test (extend it with one assertion).

### A.8 Verify configs/tasks/calc_lead_time.yaml (currently looks OK)
- READ: pipelines/calculations/lead_time.py and tests/unit/test_lead_time_logic.py
- Confirm description matches what the file actually does; adjust if not.
- Check required_files has no YAML structure bugs.

### A.9 Verify configs/tasks/optimize_polars_query.yaml
- READ: pipelines/calculations/cumulative_flow.py and tests/unit/test_cumulative_flow.py
- Same confirmation + YAML structure check.

### A.10 Clean up stray config files
DELETE: configs/test_suite.yaml (Gemini's test artifact, not needed)
DELETE: configs/test_sweep.yaml (same)
These are the only files the implementer should delete; all others stay.

### A.11 ACCEPTANCE GATE
- `uv run python main.py --dry-run --task-suite configs/task_suites/python_core_v1.yaml
   --runs 1 --config-ids 02_claude_code_like` runs without error (dry-run validates task
   loading including required_files existence check from config_loader).
- YAML lint: `python -c "import yaml; [yaml.safe_load(open(f)) for f in
   __import__('glob').glob('configs/tasks/*.yaml')]"` exits 0 (structure is valid).
- `uv run pytest tests/ -q` still 177+ green.

================================================================================
## PHASE B — Cross-task external validity (Friedman + Nemenyi)
================================================================================

CREATE FILE: src/features/cross_task.py

Implement the following (pure Python + numpy only; guard scipy import):

```python
"""
Cross-task statistical aggregation for external validity.

Implements the Friedman test and Nemenyi post-hoc critical difference for
ranking tool configs across multiple tasks. Reference:
  Demšar (2006), "Statistical Comparisons of Classifiers over Multiple Data Sets",
  Journal of Machine Learning Research 7, 1–30.
"""
```

Functions to implement (ALL with full type hints and docstrings):

1. `def build_rank_matrix(
       per_task_results: dict[str, dict[str, float]]
   ) -> dict[str, dict[str, float]]`:
   - Input: {task_name -> {config_id -> median_net_spt}}. Missing entries = NaN.
   - For each task, rank configs from best (rank=1) to worst. Use average rank for ties.
   - Return {config_id -> {task_name -> rank}}.
   NOTE: only include (config_id, task) cells where the config has status OK or
   LOW_CONFIDENCE (caller is responsible for filtering; just handle NaN gracefully).

2. `def average_ranks(rank_matrix: dict[str, dict[str, float]]) -> dict[str, float]`:
   - For each config, mean rank across tasks where it has a valid entry.
   - Return {config_id -> avg_rank}. Lower is better (rank 1 = best).

3. `def friedman_test(rank_matrix: dict[str, dict[str, float]]) -> tuple[float, float, int, int]`:
   - Friedman chi-square statistic + p-value + (k configs, n tasks).
   - Use the standard formula: chi2_F = (12n)/(k(k+1)) * (sum_j R_j^2 - k(k+1)^2/4)
     where R_j = sum of ranks for config j across n tasks.
   - p-value via chi2 CDF with df = k-1 (use scipy if available, else a simple chi2 table
     covering common k values 2..21 at alpha=0.05; or implement the regularized gamma).
   - Return (stat, p_value, k, n).

4. Q_ALPHA_TABLE: dict[int, float] — Studentized range statistic / sqrt(2) for alpha=0.05.
   Standard Nemenyi table (Demšar 2006, Table 5):
   k=2: 1.960, k=3: 2.343, k=4: 2.569, k=5: 2.728, k=6: 2.850, k=7: 2.949,
   k=8: 3.031, k=9: 3.102, k=10: 3.164, k=11: 3.219, k=12: 3.268, k=13: 3.313,
   k=14: 3.354, k=15: 3.391, k=16: 3.424, k=17: 3.456, k=18: 3.485, k=19: 3.513,
   k=20: 3.539

5. `def nemenyi_cd(k: int, n: int, alpha: float = 0.05) -> float`:
   - CD = Q_ALPHA_TABLE[k] * sqrt(k*(k+1) / (6*n))
   - Raise ValueError if k not in table.

6. `def group_by_cd(
       avg_ranks: dict[str, float], cd: float
   ) -> list[list[str]]`:
   - Sort configs by avg_rank ascending.
   - Group: configs within CD of each other (|rank_i - rank_j| <= CD) form a group.
   - Use a simple connected-components approach: two configs in the same group if their
     rank difference <= CD; groups can overlap (standard presentation).
   - Return list of groups (each group is a list of config_ids), ordered by group's
     min rank. A config may appear in multiple overlapping groups.

7. `def cross_task_report(
       per_task_results: dict[str, dict[str, float]],
       alpha: float = 0.05
   ) -> dict`:
   - Orchestrates build_rank_matrix, average_ranks, friedman_test, nemenyi_cd, group_by_cd.
   - Returns:
     {
       "rank_matrix": {...},
       "avg_ranks": {...},            # sorted by rank
       "friedman_stat": float,
       "friedman_p": float,
       "k": int, "n": int,
       "cd": float,
       "cd_groups": [[...], ...],     # from group_by_cd
       "consistent_winners": [...],   # configs in the best rank group, separated from next by > CD
       "win_rate": {config_id: float}, # fraction of tasks where config has rank 1
       "is_significant": bool,        # friedman_p < alpha
     }

8. `def rank_stability(
       per_model_avg_ranks: dict[str, dict[str, float]]
   ) -> dict`:
   - Input: {model_name -> avg_ranks_dict} (from average_ranks per model).
   - Compute pairwise Spearman correlation of the rank vectors (common configs only).
   - Return {
       "correlations": {(m1,m2): rho, ...},
       "mean_correlation": float,
       "stable_winners": [configs that appear in top CD group for all models]
     }

Implementation note: Spearman correlation = Pearson on ranks. Implement it with numpy
(already a dependency). Do NOT import scipy for correlation.

### PHASE B ACCEPTANCE GATE
Tests to add in tests/features/test_cross_task.py (NOT tests/unit/):
- test_build_rank_matrix: two tasks, three configs, verify rank assignments.
- test_friedman_and_cd: synthetic 3-config/4-task matrix where one config always ranks
  first -> significant p, that config is the consistent winner.
- test_friedman_equal: all configs tied on every task -> p close to 1.0 (not significant).
- test_nemenyi_cd_math: verify CD formula for k=3, n=5 against hand calculation.
- test_group_by_cd: overlapping groups when some configs are within CD of each other.
- test_cross_task_report_integration: end-to-end with synthetic data.
- `uv run pytest tests/ -q` green (count must be >= 183, i.e., 177 + 6 new tests).

================================================================================
## PHASE C — Budget config + Protocol doc
================================================================================

### C.1 CREATE: configs/budget.yaml
```yaml
# Budget limits for benchmark runs.
# CLI flags (--max-config-usd etc.) override these values.
max_config_usd: 0.40          # per single config execution
max_tokens_per_config: 600000 # per single config execution (cycle runaway guard)
max_session_usd: 8.0          # per (model, task) suite — all configs × n_runs
max_matrix_usd: 50.0          # across the entire models × tasks matrix
```

MODIFY: src/core/config_loader.py
- Add `def load_budget_config(path: str) -> dict[str, float]` returning the four keys above
  with their defaults if the file doesn't exist. Already-existing tests must stay green.

MODIFY: main.py
- Add `--budget-config` flag defaulting to `configs/budget.yaml`.
- When budget.yaml exists, load it and use as defaults for --max-config-usd,
  --max-session-usd, --max-matrix-usd, --max-tokens-per-config, so CLI overrides still work.
- Thread max_session_usd to BenchmarkOrchestrator (as max_suite_usd kwarg; already in
  the **_kwargs path at benchmark.py:107).
- Thread max_tokens_per_config to BenchmarkOrchestrator (same path).
- Thread max_matrix_usd to MatrixOrchestrator (already accepted as constructor arg).

### C.2 CREATE: docs/BENCHMARK_PROTOCOL.md
Content — write as proper Markdown (no code only, prose + code blocks):

# Benchmark Protocol

## Purpose
Token-economy benchmarking: which tools allow an LLM agent to solve Python coding tasks while
consuming the fewest tokens, while maintaining task quality?

## Scope limitations
- One codebase (process_metrics_platform_v2)
- Results are valid for: "tool X is [more/less] token-efficient for [category of] Python tasks
  on [this codebase], with [model]". NOT: "tool X is universally better".
- External validity requires >= 10 diverse tasks (see python_core_v1 suite).

## Running modes (cheapest to most expensive)

### 1. Smoke run (~$0.02–0.04 per config, zero statistical weight)
```
python main.py --runs 1 --dry-run                       # zero cost, functional test
python main.py --runs 1 --config-ids 02_claude_code_like # single config, one real run
```
Use for: verifying the benchmark pipeline works end-to-end.

### 2. Per-task internal significance (5–7 runs per config)
```
python main.py --runs 6                                   # all 21 configs × 6 runs
python main.py --runs 6 --config-ids 09_rg 14_repo_map   # subset
```
Output: per-config bootstrap CI, validity status (OK/LOW_CONFIDENCE/UNSTABLE/INSUFFICIENT).
Configs with overlapping 90% CI = statistically indistinguishable — do NOT claim "X is N× better".

### 3. Task sweep (one model, all tasks) — external validity for that model
```
python main.py --estimate --task-suite configs/task_suites/python_core_v1.yaml --runs 6
python main.py --task-suite configs/task_suites/python_core_v1.yaml --runs 6
```
Output: per-task CI + cross-task Friedman/Nemenyi (cd_groups, consistent_winners).
Friedman p < 0.05 = tools are NOT equivalent across tasks; Nemenyi CD shows which groups differ.

### 4. Full matrix (4 models × 10 tasks × 21 configs × 6 runs ≈ 5040 runs, ~$100)
Always estimate first:
```
python main.py --estimate --matrix --task-suite configs/task_suites/python_core_v1.yaml \
  --models configs/model_sweep.yaml --runs 6
python main.py --matrix --task-suite configs/task_suites/python_core_v1.yaml \
  --models configs/model_sweep.yaml --runs 6 --yes
```
Output: cross-task Friedman per model + cross-model stability (Spearman rank correlation).
If rank correlation across models is high (rho > 0.8), the tool ranking is model-agnostic.

## Budget safety
- Default caps: $0.40/config, $8/session, $50/matrix (configs/budget.yaml).
- Override: --max-config-usd, --max-session-usd, --max-matrix-usd.
- agent_runaway flag fires when: token_exceeded OR tool_errors > 10 OR agent_cycles > 40.
  Runaway runs are excluded from aggregation (multi_run.py).
- ALWAYS run --estimate before a paid matrix run and check projected USD < max_matrix_usd.

## Statistical interpretation
- Single run: point estimate only. No claims about significance.
- 5+ runs per config: bootstrap 90% CI on net_spt (schema-overhead-adjusted SPT).
  Status OK: CI computed, n_valid >= 4, CV < 0.5. Use for ranking.
  Status LOW_CONFIDENCE: n_valid = 3 or CI wide. Use with caution.
  Status UNSTABLE (CV > 0.5) or INSUFFICIENT_DATA (n_valid <= 2): excluded from ranking table.
- Cross-task significance: Friedman chi² test (p < 0.05 = configurations differ); Nemenyi
  post-hoc critical difference (CD) shows which pairs are statistically distinguishable.
  If all pairwise |rank_i - rank_j| < CD, no tool is significantly better than any other.

## Adding tasks
See docs/TASK_AUTHORING.md for the task authoring guide and the memory-proof rule.

### C.3 ACCEPTANCE GATE
- `uv run pytest tests/ -q` green (count >= 183, same or more than after Phase B).
- `python main.py --help` shows `--budget-config` flag.
- `python main.py --estimate --runs 1` prints the estimate with budget cap (reads from
  configs/budget.yaml if present).

================================================================================
## PHASE D — Cleanup
================================================================================

### D.1 Move new tests to correct location
The benchmark framework puts tests in tests/features/ and tests/core/ — NOT tests/unit/.
MOVE (git mv) the four new test files:
  tests/unit/test_phase_1_metrics.py   -> tests/features/test_phase_1_metrics.py
  tests/unit/test_phase_2_significance.py -> tests/features/test_phase_2_significance.py
  tests/unit/test_phase_3_suites.py   -> tests/features/test_phase_3_suites.py
  tests/unit/test_phase_4_sweep.py    -> tests/features/test_phase_4_sweep.py
Remove tests/unit/ if it becomes empty after the move.

### D.2 Update pyproject.toml testpaths if needed
Check pyproject.toml for `testpaths`. If it only lists specific directories and omits
tests/unit or tests/features, update accordingly.

### D.3 ACCEPTANCE GATE
- `uv run pytest tests/ -q` green (same count; pytest still finds all tests).
- `ls tests/unit/` should not exist or be empty.

================================================================================
## FILES SUMMARY
================================================================================

MODIFY (task YAMLs — all 7 must be corrected):
  configs/tasks/fix_jira_mapping.yaml
  configs/tasks/add_sprint_metric.yaml
  configs/tasks/add_unit_test_coverage.yaml
  configs/tasks/change_func_signature.yaml
  configs/tasks/extract_const_pipeline.yaml
  configs/tasks/fix_csv_export_bug.yaml
  configs/tasks/update_api_schema.yaml
  (calc_lead_time.yaml and optimize_polars_query.yaml — verify, fix if needed)

DELETE:
  configs/test_suite.yaml
  configs/test_sweep.yaml

CREATE:
  src/features/cross_task.py
  tests/features/test_cross_task.py  (6+ tests covering friedman, nemenyi, rank_matrix, etc.)
  configs/budget.yaml
  docs/BENCHMARK_PROTOCOL.md

MOVE:
  tests/unit/test_phase_1_metrics.py   -> tests/features/
  tests/unit/test_phase_2_significance.py -> tests/features/
  tests/unit/test_phase_3_suites.py   -> tests/features/
  tests/unit/test_phase_4_sweep.py    -> tests/features/

MODIFY:
  src/core/config_loader.py  (add load_budget_config)
  main.py  (--budget-config flag, load and apply budget defaults)

## HARD ACCEPTANCE (whole plan)
1. `uv run pytest tests/ -q` fully green — count >= 183.
2. All 10 task YAMLs have valid YAML structure (required_files = only file paths, not text).
3. All required_files paths in task YAMLs exist in the target repo at
   C:\Users\User\a_projects\process_metrics_platform_v2.
4. `python main.py --estimate --matrix --task-suite configs/task_suites/python_core_v1.yaml
   --models configs/model_sweep.yaml --runs 6` shows projected USD/tokens and exits 0.
5. `python -c "import src.features.cross_task as ct; print(ct.__doc__)"` prints the module
   docstring — confirms the module imports cleanly.
6. `ls docs/BENCHMARK_PROTOCOL.md configs/budget.yaml` — both exist.
