# Plan: Benchmark Credibility Overhaul

Date: 2026-05-31
Project: tools_token_economy
Goal: Make the benchmark statistically trustworthy. Fix the task (currently solvable from
model memory), fix the eval_score bug, upgrade the judge, add multi-provider support, and
add variance-aware statistical protection across 5 runs.

IMPORTANT EXECUTION NOTE FOR IMPLEMENTER:
- Work PHASE BY PHASE in the order given. Each phase has an acceptance gate. Do not start a
  later phase until the prior gate passes.
- After each phase, run `uv run pytest tests/ -q` (in WSL via `bash scripts/run_wsl.sh` is NOT
  needed for unit tests; plain `uv run pytest` is fine) and report pass/fail.
- Do NOT run the full paid benchmark. Only dry-runs and unit tests. The user runs the paid
  benchmark manually after review.
- Target benchmark repo lives at C:\Users\User\a_projects\process_metrics_platform_v2
  (WSL path is /c/Users/User/... NOT /mnt/c/...).

================================================================================
## CONTEXT: Root-cause findings (already verified in source)
================================================================================

1. Current task ("Bearer case-insensitive") is solvable from model training memory.
   PROOF: config 21_bash_only solved it with files_read=0, precision=0, recall=0, success=true.
   The benchmark currently measures model memory, not tool quality.

2. eval_score is a misnamed binary mirror of success.
   LOCATION: src/features/agent_integration/agno_runner.py lines 713, 847, 862 and
   src/orchestrator/benchmark.py line 359 all set `eval_score=1.0 if success else 0.0`.
   The real composite (compute_composite) is computed only in the dashboard, never stored.
   RESULT: 18_rg_repo_map shows eval_score=1.0 despite task_solved=0.6.

3. temperature=0.0 and seed=42 are ALREADY set in configs/provider.yaml, yet rg varied
   3.6K -> 106K tokens between runs. Agentic-loop determinism is unachievable via temperature.
   The fixed seed=42 also creates FALSE stability if reused across runs.

4. Judge = agent (both gpt-4.1-mini). context_quality_score=0.75 for 15/21 configs = the
   "unsure" default. No real discrimination. Self-evaluation bias.

5. Statistical infra ALREADY EXISTS but unused: src/features/multi_run.py has
   aggregate_session() with p25/p50/p75 percentiles. --runs flag exists in main.py.

6. Agno 2.6.9 (installed) has native model classes for all wanted providers:
   agno.models.openai.OpenAIChat, .openai.like.OpenAILike (universal OpenAI-compatible base),
   .anthropic (Claude), .google (Gemini), .openrouter.OpenRouter, .dashscope.DashScope (Qwen).
   Judge currently uses raw `openai.OpenAI` client (llm_judge.py:156) which supports base_url.

================================================================================
## PHASE 0: New task — repo-specific, env-free, memory-proof
================================================================================

### 0.1 Create the task definition
CREATE FILE: configs/tasks/aging_stale.yaml

Model it on configs/tasks/medium.yaml. Content:

```yaml
difficulty: hard
name: "Work item aging: add is_stale flag"
description: |
  The Work Item Aging calculation in pipelines/calculations/aging.py computes, for each
  active (unresolved) issue, how many days it has spent in its current status
  (column: age_in_status_days).

  Product wants to highlight items that have stagnated. Add a new boolean output column
  named `is_stale` to the aging facts result. An issue is stale when its
  age_in_status_days is strictly greater than 14 days.

  Requirements:
  - Define a module-level constant STALE_AGE_THRESHOLD_DAYS = 14 in aging.py and use it.
  - The `is_stale` column MUST be present in EVERY DataFrame the function returns, including
    the early empty-result branch that declares an explicit schema (use pl.Boolean there).
  - Do NOT change existing column names or the meaning of age_days / age_in_status_days.
  - Add ONE regression test at the END of tests/unit/test_aging.py that builds an active
    issue with age_in_status_days > 14 and asserts is_stale is True, plus one with
    age_in_status_days <= 14 asserting False. Do not insert it inside another function.
  - All pre-existing tests in tests/unit/test_aging.py MUST still pass.
test_cmd: "uv run --extra dev pytest tests/unit/test_aging.py -q"
timeout_sec: 600
target_file: "tests/unit/test_aging.py"
required_files:
  - "pipelines/calculations/aging.py"
  - "pipelines/calculations/commitment_resolver.py"
  - "tests/unit/test_aging.py"
success_criteria:
  - "aging output includes is_stale boolean column in all return paths"
  - "is_stale is True iff age_in_status_days > 14"
  - "All pre-existing aging tests pass"
```

WHY THIS TASK:
- Pure Polars function, no env vars, no DB — deterministic and understandable.
- Repo-specific bespoke domain logic (commitment points, cross-project leakage) that is NOT
  in any model's training data, unlike the Bearer pattern.
- Has multiple return points (an explicit-schema empty branch + the main path) — an agent that
  doesn't actually read/understand the file will miss the empty-schema branch and fail the
  empty-input test. This is the natural difficulty/discriminator.
- Verifiable by a deterministic pytest.

### 0.2 Point the benchmark at the new task
MODIFY: wherever the active task file is selected. Search for "tasks/medium.yaml" across the
repo (grep) — likely in main.py, src/orchestrator/benchmark.py, or a config. Add a CLI/config
switch `--task <name>` if not present; default should remain configurable. Keep medium.yaml
available so we can run BOTH (memory task vs repo-specific task) for comparison.

### 0.3 ACCEPTANCE GATE (canary — memory-proof validation)
This gate runs REAL API calls but only for 2 configs, so cost is tiny. The user will run it;
implementer just wires a helper command:
- Run ONLY 21_bash_only and 05_read_only on aging_stale task.
- RULE: if 21_bash_only returns success=true with files_read < 2 → TASK IS INVALID (in model
  memory). Stop and report; we pick a fallback task.
- Fallback task candidates (env-free, repo-specific), in order:
  1. pipelines/calculations/backlog_growth.py — add a derived ratio column + test
  2. pipelines/calculations/cycle_time_ext.py — add a percentile column + test
- Add an automated detector (see Phase 3, parametric_success flag) so this is measured, not eyeballed.

================================================================================
## PHASE 1: Fix eval_score (correctness bug #2)
================================================================================

### 1.1 Create a shared scoring module
CREATE FILE: src/core/scoring.py
- Move/duplicate the composite logic so runner does not import from dashboard_builder.
- Functions:
  - `eval_weights() -> dict[str,float]` : load from configs/benchmark_weights.yaml (reuse
    existing loader in dashboard_builder.load_weights_config; import or factor out).
  - `compute_eval_composite(judge_scores: dict, weights: dict, success: bool) -> float`:
    returns 0.0 if not success; else weighted geometric mean of the 7 judge dimensions
    (same formula as dashboard_builder.compute_composite). This makes success a hard gate
    AND folds in judge quality.

### 1.2 Replace the binary assignments
MODIFY: src/features/agent_integration/agno_runner.py lines 713, 847, 862
MODIFY: src/orchestrator/benchmark.py line 359
- Replace `eval_score=1.0 if success else 0.0` with
  `eval_score=compute_eval_composite(judge_scores, eval_weights(), success)`.
- Keep a separate stored field `success_binary: bool` (add to RunMetrics in
  src/core/models.py if not present) so success and the composite are never conflated again.
- IMPORTANT: judge scores may be produced AFTER the runner builds RunMetrics. If so, compute
  eval_score at the point where judge results are merged into RunMetrics (find where judge
  output is attached — grep "judge_task" or "task_solved_score" assignment). Set eval_score there.

### 1.3 ACCEPTANCE GATE
- Add/adjust a unit test in tests/features/ that asserts: a config with task_solved=0.6 and
  other dims ~0.5 produces eval_score < 0.7 (NOT 1.0).
- `uv run pytest tests/ -q` green.

================================================================================
## PHASE 2: Multi-provider model infrastructure
================================================================================

### 2.1 Provider factory
CREATE FILE: src/core/provider_factory.py
- Function `build_agent_model(cfg: ProviderConfig)` returning an Agno model instance.
- Map `cfg.provider` -> Agno class:
  - "openai"      -> agno.models.openai.OpenAIChat(id=cfg.model, ...)
  - "anthropic"   -> agno.models.anthropic.Claude(id=cfg.model, ...)
  - "google"/"gemini" -> agno.models.google.Gemini(id=cfg.model, ...)
  - "openrouter"  -> agno.models.openrouter.OpenRouter(id=cfg.model, ...)
  - "qwen"/"dashscope" -> agno.models.dashscope.DashScope(id=cfg.model, ...)
  - "compatible"/"custom" -> agno.models.openai.like.OpenAILike(id=cfg.model,
        base_url=cfg.api_base, api_key=os.getenv(cfg.api_key_env))
- Each branch must pass through: temperature, seed, max_tokens, and api_key resolved from
  `cfg.api_key_env` (default per provider: OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY,
  OPENROUTER_API_KEY, DASHSCOPE_API_KEY). For "compatible", api_base + api_key_env are required.
- Raise a clear error listing supported providers if unknown.

### 2.2 Extend ProviderConfig + provider.yaml
MODIFY: src/core/models.py (ProviderConfig dataclass) and the config loader.
MODIFY: configs/provider.yaml to the new schema (keep backward-compatible defaults):

```yaml
# Agent model (the system under test)
provider: "openai"            # openai | anthropic | google | openrouter | qwen | compatible
model: "gpt-4.1-mini"
api_base: ""                  # only for provider: compatible
api_key_env: "OPENAI_API_KEY" # env var holding the key
temperature: 0.0
seed: 42                      # base seed; per-run offset applied (see Phase 4)
max_steps: 50
max_iterations: 50

# Judge model (must differ from agent to avoid self-evaluation bias)
judge:
  provider: "openai"
  model: "gpt-5.1-mini"       # direct OpenAI Platform, NOT via OpenRouter
  api_base: ""
  api_key_env: "OPENAI_API_KEY"
  temperature: 0.0
  self_consistency: 1         # number of judge samples (median); 1 = single call
```

### 2.3 Wire the factory into the agent runner
MODIFY: src/features/agent_integration/agno_runner.py line ~360 (and ~the second OpenAIChat
construction if any). Replace direct `OpenAIChat(...)` with `build_agent_model(self.provider_cfg)`.
Preserve seed/temperature/max_tokens passing.

### 2.4 ACCEPTANCE GATE
- Unit test: build_agent_model returns the correct class for each provider string (mock env keys).
- `uv run pytest tests/ -q` green. No live calls needed here.

================================================================================
## PHASE 3: Judge upgrade + validity flags
================================================================================

### 3.1 Judge model via config + base_url support
MODIFY: src/features/llm_judge.py
- Line ~154-156: read judge config from ProviderConfig.judge (provider/model/api_base/api_key_env)
  instead of only `os.getenv("JUDGE_MODEL", "gpt-4.1-mini")`.
- Build the OpenAI client with optional base_url:
  `OpenAI(api_key=os.getenv(judge.api_key_env), base_url=judge.api_base or None)`.
  For provider=openai with empty api_base this is identical to today. This keeps the judge on
  the OpenAI-compatible chat.completions path (works for OpenAI direct, OpenRouter, Qwen, Gemini-compat).
- Default judge model: "gpt-5.1-mini".

### 3.2 Judge self-consistency (optional, config-gated)
- If judge.self_consistency > 1: call each judge dimension N times at temperature 0 and take
  the MEDIAN score. Removes judge noise. Keep N=1 default to control cost.

### 3.3 Validity flags on RunMetrics
MODIFY: src/core/models.py (add fields) and src/features/agent_integration/agno_runner.py
(compute them):
- `parametric_success: bool` = success and retrieval_precision == 0 and retrieval_recall == 0
  and files_read < 2  -> "solved without reading code" (memory answer). 
- `agent_runaway: bool` = token_exceeded or tool_errors > 10 or agent_cycles > 40.
- `telemetry_ok: bool` = usage metrics were successfully parsed (see Phase 5).
These feed the statistical gate in Phase 4 (excluded from ranking).

### 3.4 ACCEPTANCE GATE
- Unit tests for the three flags (construct RunMetrics-like dicts, assert flags).
- `uv run pytest tests/ -q` green.

================================================================================
## PHASE 4: Statistical significance — 5 runs + insufficient-runs protection
================================================================================

Design principle: 5 runs is the BUDGET, not a guarantee of significance. The protection layer
decides whether 5 runs are ENOUGH per config, and refuses to rank configs whose results are
too noisy or too few.

### 4.1 Per-run seed variation (kill false determinism)
MODIFY: wherever seed is passed to the model (agno_runner ~360 and provider_factory).
- Use `effective_seed = base_seed + run_index`. run_index must be threaded from the multi-run
  orchestrator into each config execution. This ensures the 5 runs are genuinely independent
  samples, not 5 identical replays.

### 4.2 Statistics module
CREATE FILE: src/features/stats.py
- `coefficient_of_variation(values) -> float` = std/mean (guard mean==0).
- `bootstrap_ci(values, statistic=median, n=2000, alpha=0.10) -> (lo, hi)` : 90% CI via
  resampling. Use numpy (already a dep — multi_run.py imports np).
- `ci_overlap(ci_a, ci_b) -> bool` : do two intervals overlap?
- `rank_confidence(values) -> dict` : returns {median, p25, p75, cv, ci_lo, ci_hi, n_valid}.

### 4.3 Validity-weighted aggregation + insufficient-data gate
MODIFY: src/features/multi_run.py aggregate_session()
- Before aggregating a config, FILTER OUT invalid runs:
  exclude runs where parametric_success OR agent_runaway OR not telemetry_ok.
- Let n_valid = count of remaining runs. Apply this gate:
  - n_valid >= 4  -> status "OK", compute full stats + bootstrap CI.
  - n_valid == 3  -> status "LOW_CONFIDENCE", compute stats but flag.
  - n_valid <= 2  -> status "INSUFFICIENT_DATA", NO rank assigned, report median only with warning.
- Compute CV of total_tokens and of the primary metric (SPT / net_spt). If CV > 0.5 ->
  status downgraded to "UNSTABLE" regardless of n_valid (the config's behavior is not
  reproducible enough to rank).
- Store per-config: n_total_runs, n_valid_runs, status, cv, ci. Add these to the aggregated
  output dict and to RunMetrics aggregation schema.

### 4.4 Adaptive top-up recommendation (no auto-spend)
- When a config ends UNSTABLE or LOW_CONFIDENCE, the aggregator writes a recommendation field
  `suggested_additional_runs` (e.g. 3) into the session meta. Do NOT auto-run (cost control);
  surface it so the user can re-run those config-ids with --retry/--runs.
- main.py: print a summary at end listing configs needing more runs.

### 4.5 Ranking rule (significance-aware)
MODIFY: dashboard_builder.py ranking + streamlit_app.py display.
- Two configs are declared "different" on a metric ONLY if their 90% bootstrap CIs do not
  overlap. Otherwise show them as a tie-band.
- Configs with status INSUFFICIENT_DATA / UNSTABLE are shown in a separate "not ranked" section.

### 4.6 Default runs = 5
MODIFY: main.py --runs default to 5 (keep overridable). Update configs/provider.yaml comment.

### 4.7 ACCEPTANCE GATE
- Extend tests/features/test_multi_run.py: feed synthetic 5-run sessions covering each status
  (OK / LOW_CONFIDENCE / INSUFFICIENT_DATA / UNSTABLE) and assert the gate + CI logic.
- `uv run pytest tests/ -q` green.

================================================================================
## PHASE 5: Telemetry robustness + honest metrics
================================================================================

### 5.1 Fix telemetry_corrupt (03_gemini_like lost $0.079 with zero metrics)
MODIFY: src/features/agent_integration/agno_runner.py — find where usage/token metrics are
parsed from the Agno response. Wrap in explicit extraction with a fallback:
- If usage fields are missing/zero but the agent produced output, attempt a secondary
  extraction (Agno response.metrics / message usage). 
- If still unparseable: set execution_result="telemetry_failed", telemetry_ok=False. Do NOT
  silently report 0 tokens as a valid datapoint, and do NOT label it "context explosion".

### 5.2 Token decomposition (fair tool comparison)
MODIFY: src/core/models.py + agno_runner.py:
- `schema_overhead_tokens` = tool_schema_bytes-derived estimate * model_calls (approx tokens
  for tool schemas resent each call). Use a bytes->tokens ratio ~4 bytes/token.
- `reasoning_tokens` = max(input_tokens - schema_overhead_tokens, 0).
- `net_spt` = success / (reasoning_tokens / 1000) when reasoning_tokens > 0 else 0.
  Add to RunMetrics and to benchmark_weights / dashboard as a SECONDARY headline metric so a
  rich-API tool (Serena) is not penalized purely for schema size.

### 5.3 ACCEPTANCE GATE
- Unit test for net_spt / schema_overhead math.
- `uv run pytest tests/ -q` green.

================================================================================
## PHASE 6: Prompt symmetry for all tools (remove confound)
================================================================================

MODIFY: configs/tools.yaml — tool_restriction_prefix for ALL configs.
- Give EVERY config a short, equally-detailed "how to use your tools well" prefix (1-2
  concrete usage examples for its specific tools). This removes the confound where grep tools
  had implicit training-data advantage and semantic tools (16-20) were under-instructed.
- For 16-20 (Serena/Semble) specifically: show one concrete call
  (e.g. find_symbol -> find_referencing_symbols) and explicitly forbid falling back to
  shell/grep/read for navigation.
- Symmetry requirement: the prompt template must be the SAME LENGTH/STRUCTURE across configs;
  only the tool names/examples differ. Document this in a comment so reviewers can verify no
  config got a richer prompt than another.

ACCEPTANCE GATE: `uv run python main.py --dry-run` loads all 21 configs without error.

================================================================================
## PHASE 7: README + docs honesty
================================================================================

MODIFY: README.md and README_RU.md (after the real re-run; for now just structure):
- Replace the single-run cherry-picked table with: all 21 configs, each showing
  median SPT with 90% CI, status (OK/UNSTABLE/INSUFFICIENT), n_valid/n_total.
- Two task sections: "memory task (medium)" vs "repo-specific task (aging_stale)".
- State explicitly: configs whose CIs overlap are statistically indistinguishable.
- Remove any "Nx better" claim not backed by non-overlapping CIs.
- Document judge model (gpt-5.1-mini) and that judge != agent.
NOTE: leave the numbers as TODO placeholders; the user runs the paid benchmark and fills them.

================================================================================
## FILES SUMMARY
================================================================================

CREATE:
- configs/tasks/aging_stale.yaml
- src/core/scoring.py
- src/core/provider_factory.py
- src/features/stats.py

MODIFY:
- configs/provider.yaml (multi-provider + judge schema, runs note)
- configs/tools.yaml (symmetric prompts)
- src/core/models.py (ProviderConfig fields, RunMetrics new fields)
- src/features/agent_integration/agno_runner.py (eval_score, factory, seed offset, telemetry,
  token decomposition, validity flags)
- src/orchestrator/benchmark.py (eval_score line 359, task selection, run_index threading)
- src/features/llm_judge.py (judge config + base_url + self-consistency)
- src/features/multi_run.py (validity-weighted aggregation, status gate, CI)
- src/features/dashboard_builder.py (significance-aware ranking)
- streamlit_app.py (display CI, status, not-ranked section)
- main.py (--task switch, --runs default 5, top-up summary)
- README.md, README_RU.md (structure only, numbers TODO)

CONFIG LOADER: update wherever provider.yaml is parsed to read the new fields.

================================================================================
## OUT OF SCOPE / DO NOT DO
================================================================================
- Do NOT run the full paid benchmark (only --dry-run and unit tests).
- Do NOT delete medium.yaml (kept for comparison).
- Do NOT commit secrets. All keys via env vars named in api_key_env.
- Do NOT change the target repo (process_metrics_platform_v2) — the agent does that at runtime
  inside an isolated worktree.
