# Plan: Benchmark Credibility — Remaining Phases 3–6

Date: 2026-05-31
Project: tools_token_economy
Status: Phases 0–2 already implemented. This plan covers ONLY phases 3–6.

IMPORTANT FOR IMPLEMENTER:
- Read this file fully before starting.
- Do NOT redo work from phases 0–2 (already done — do not touch scoring.py, provider_factory.py,
  aging_stale.yaml, provider.yaml judge section, or the eval_score fix in benchmark.py).
- After ALL phases, run `uv run pytest tests/ -q` and report pass/fail counts.
- Do NOT run the paid benchmark. Only unit tests and --dry-run.
- WSL path for the project is /c/Users/User/a_projects/tools_token_economy (NOT /mnt/c).

================================================================================
## CURRENT STATE (already done — do not repeat)
================================================================================
- src/core/scoring.py — compute_eval_composite(), eval_weights() ✓
- src/core/provider_factory.py — build_agent_model() for all providers ✓
- src/core/models.py — JudgeConfig, ProviderConfig.judge, success_binary field ✓
- configs/tasks/aging_stale.yaml — new memory-proof task ✓
- configs/provider.yaml — judge section with gpt-5.1-mini ✓
- benchmark.py — eval_score overwritten via compute_eval_composite after judge ✓
- main.py — --task-name / --task-config flags, aging_stale as default ✓
- benchmark.py — seed = base_seed + rep_index (partial) ✓

================================================================================
## PHASE 3: Validity flags on RunMetrics + judge wired to config
================================================================================

### 3.1 Add validity fields to RunMetrics
FILE: src/core/models.py

Find the RunMetrics class (it's a Pydantic BaseModel). Add these fields with defaults:

    parametric_success: bool = False
    agent_runaway: bool = False
    telemetry_ok: bool = True

### 3.2 Compute validity flags in agno_runner.py
FILE: src/features/agent_integration/agno_runner.py

After run_metrics is constructed (the RunMetrics(...) call that currently sets eval_score),
add computation of the three flags using model_copy or by passing them to the constructor:

    parametric_success = (
        run_metrics.success
        and run_metrics.retrieval_precision == 0.0
        and run_metrics.retrieval_recall == 0.0
        and run_metrics.files_read < 2
    )
    agent_runaway = (
        run_metrics.token_exceeded
        or run_metrics.tool_errors > 10
        or run_metrics.agent_cycles > 40
    )
    telemetry_ok = (run_metrics.total_tokens > 0)

Then update run_metrics with these computed values.

NOTE: retrieval_precision and retrieval_recall are set LATER in benchmark.py, not in the runner.
So compute parametric_success in benchmark.py AFTER the retrieval metrics update block
(around line 354 in benchmark.py, after the model_copy that sets retrieval_precision/recall).
agent_runaway and telemetry_ok can be computed in the runner.

### 3.3 Wire judge to use JudgeConfig from provider.yaml
FILE: src/features/llm_judge.py

Current state: judge reads JUDGE_MODEL env var, defaults to "gpt-4.1-mini".
Goal: judge reads from ProviderConfig.judge (JudgeConfig).

Find the LLMJudge __init__ (around line 153). It currently does:
    self.judge_model = judge_model or os.getenv("JUDGE_MODEL", "gpt-4.1-mini")
    self.client = OpenAI(api_key=self.api_key) if self.api_key else None

Change to accept an optional JudgeConfig parameter:
    def __init__(self, judge_config: JudgeConfig | None = None, judge_model: str | None = None):
        # Prefer JudgeConfig if given
        if judge_config is not None:
            self.judge_model = judge_config.model
            api_key = os.getenv(judge_config.api_key_env)
            base_url = judge_config.api_base or None
            self.self_consistency = judge_config.self_consistency
        else:
            self.judge_model = judge_model or os.getenv("JUDGE_MODEL", "gpt-5.1-mini")
            api_key = os.getenv("OPENAI_API_KEY")
            base_url = None
            self.self_consistency = 1
        self.client = OpenAI(api_key=api_key, base_url=base_url) if api_key else None

Wire this in benchmark.py where LLMJudge is instantiated:
    judge = LLMJudge(judge_config=self.provider_config.judge)

### 3.4 Add parametric_success to benchmark.py after retrieval update
FILE: src/orchestrator/benchmark.py

After the block that sets retrieval_precision/recall (model_copy around line 354), add:
    # Compute parametric_success flag
    ps = (
        run_metrics.success
        and run_metrics.retrieval_precision == 0.0
        and run_metrics.retrieval_recall == 0.0
        and getattr(run_metrics, 'files_read', 99) < 2
    )
    run_metrics = run_metrics.model_copy(update={"parametric_success": ps})

================================================================================
## PHASE 4: Statistical significance — stats.py + multi_run validity gate
================================================================================

### 4.1 Create src/features/stats.py
NEW FILE: src/features/stats.py

Content:
```python
"""Statistical utilities for benchmark run aggregation."""
from __future__ import annotations

import math
import random
from typing import Callable, Sequence


def coefficient_of_variation(values: Sequence[float]) -> float:
    """CV = std / mean. Returns inf if mean == 0, 0.0 if fewer than 2 values."""
    if len(values) < 2:
        return 0.0
    n = len(values)
    mean = sum(values) / n
    if mean == 0:
        return float("inf")
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(variance) / mean


def median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def bootstrap_ci(
    values: Sequence[float],
    statistic: Callable[[Sequence[float]], float] = median,
    n_resamples: int = 2000,
    alpha: float = 0.10,
    seed: int = 0,
) -> tuple[float, float]:
    """
    Bootstrap confidence interval at (1-alpha) level.
    Returns (lower, upper). Uses seed for reproducibility.
    """
    if len(values) < 2:
        v = values[0] if values else 0.0
        return (v, v)
    rng = random.Random(seed)
    estimates = []
    vals = list(values)
    n = len(vals)
    for _ in range(n_resamples):
        sample = [rng.choice(vals) for _ in range(n)]
        estimates.append(statistic(sample))
    estimates.sort()
    lo_idx = int(math.floor((alpha / 2) * n_resamples))
    hi_idx = int(math.ceil((1 - alpha / 2) * n_resamples)) - 1
    return (estimates[lo_idx], estimates[hi_idx])


def ci_overlap(ci_a: tuple[float, float], ci_b: tuple[float, float]) -> bool:
    """True if two CIs overlap (configs are statistically indistinguishable)."""
    return ci_a[0] <= ci_b[1] and ci_b[0] <= ci_a[1]


# Run validity statuses
STATUS_OK = "ok"
STATUS_LOW_CONFIDENCE = "low_confidence"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_UNSTABLE = "unstable"
CV_THRESHOLD = 0.5
MIN_VALID_RUNS_OK = 4
MIN_VALID_RUNS_LOW = 3


def run_validity_status(valid_values: Sequence[float]) -> str:
    """
    Determine ranking status for a config based on valid run values of a key metric
    (e.g. total_tokens or success_per_token).
    """
    n = len(valid_values)
    if n <= 2:
        return STATUS_INSUFFICIENT_DATA
    cv = coefficient_of_variation(valid_values)
    if cv > CV_THRESHOLD:
        return STATUS_UNSTABLE
    if n >= MIN_VALID_RUNS_OK:
        return STATUS_OK
    if n >= MIN_VALID_RUNS_LOW:
        return STATUS_LOW_CONFIDENCE
    return STATUS_INSUFFICIENT_DATA
```

### 4.2 Extend multi_run.py aggregate_session() with validity gate
FILE: src/features/multi_run.py

Find aggregate_session() function (around line 106). Extend it as follows:

IMPORTS to add at top of file:
    from src.features.stats import (
        coefficient_of_variation, bootstrap_ci, median, run_validity_status,
        STATUS_OK, STATUS_LOW_CONFIDENCE, STATUS_INSUFFICIENT_DATA, STATUS_UNSTABLE,
    )

INSIDE aggregate_session(), after grouping runs by config_id, for each config_id group:

1. Filter invalid runs BEFORE aggregating:
    valid_runs = [
        r for r in runs
        if not r.get("parametric_success", False)
        and not r.get("agent_runaway", False)
        and r.get("telemetry_ok", True)
    ]
    n_total = len(runs)
    n_valid = len(valid_runs)

2. Use valid_runs (not all runs) for computing metrics.

3. After computing stats for the config, determine status:
    token_values = [float(r.get("total_tokens", 0)) for r in valid_runs if r.get("total_tokens", 0) > 0]
    status = run_validity_status(token_values)

4. Compute CI for success_per_token (primary metric):
    spt_values = [float(r.get("success_per_token", 0)) for r in valid_runs]
    ci_lo, ci_hi = bootstrap_ci(spt_values) if len(spt_values) >= 2 else (0.0, 0.0)
    cv = coefficient_of_variation(spt_values) if spt_values else 0.0

5. Add to the aggregated stats dict for this config:
    stats["_n_total_runs"] = n_total
    stats["_n_valid_runs"] = n_valid
    stats["_validity_status"] = status
    stats["_spt_ci_lo"] = ci_lo
    stats["_spt_ci_hi"] = ci_hi
    stats["_spt_cv"] = cv

6. If n_valid <= 2: also set stats["_suggested_additional_runs"] = max(0, 4 - n_valid)

### 4.3 Update --runs default in main.py
FILE: main.py

Find the --runs argument (around line 159). Change default from 1 to 5:
    parser.add_argument("--runs", type=int, default=5, ...)

Also add end-of-run summary: after benchmark completes, if session results are available,
print configs where _validity_status is not STATUS_OK (UNSTABLE / INSUFFICIENT / LOW_CONFIDENCE)
with their suggested_additional_runs.

================================================================================
## PHASE 5: Token decomposition — net_spt metric
================================================================================

### 5.1 Add net_spt and schema_overhead_tokens to RunMetrics
FILE: src/core/models.py

Add to RunMetrics class:
    schema_overhead_tokens: int = 0    # approx tokens spent on tool schemas each call
    net_spt: float = 0.0               # SPT computed on reasoning tokens only (excl schema overhead)

### 5.2 Compute schema_overhead_tokens and net_spt in agno_runner.py
FILE: src/features/agent_integration/agno_runner.py

After collecting tool_schema_bytes and model_calls in run_metrics, compute:
    schema_overhead = int((tool_schema_bytes / 4) * model_calls)  # ~4 bytes per token
    reasoning_tokens = max(total_tokens - schema_overhead, 1)
    net_spt = 1000.0 / reasoning_tokens if success else 0.0

Pass these when building or updating RunMetrics.
If tool_schema_bytes is not available, default schema_overhead_tokens = 0.

================================================================================
## PHASE 6: Symmetric tool prompts for all configs (including semantic tools 16–20)
================================================================================

FILE: configs/tools.yaml

Read the current tools.yaml. For EVERY config (01 through 21), update the
tool_restriction_prefix field to include a short, equally-structured usage example block.

Format for all configs (same structure, only tool names/examples differ):
    "Use <toolname> for navigation. Example: <minimal concrete call>.
     Do NOT fall back to bash/shell/grep unless the prescribed tool fails with an error.
     Prescribed tools: <list>."

For semantic configs (16_serena_only, 17_semble_only, 18_rg_repo_map, 19_rg_lsp,
20_serena_semble), add the explicit anti-fallback instruction:
    "DO NOT use shell commands, grep, or read for code navigation.
     Use find_symbol('function_name') to locate code, then find_referencing_symbols
     to understand callers. Only use read after locating the exact file via symbol search."

IMPORTANT: All configs must get an equally-detailed prefix (same approximate token count)
so the experiment measures tool quality, not prompt quality differences.

================================================================================
## ACCEPTANCE GATES (run after each phase, report results)
================================================================================

After Phase 3:
- Confirm RunMetrics has parametric_success, agent_runaway, telemetry_ok fields
- `uv run pytest tests/core/ tests/features/test_llm_judge.py -q`

After Phase 4:
- Confirm stats.py exists and its functions are importable
- `uv run pytest tests/features/test_multi_run.py -q`

After Phase 5:
- Confirm net_spt and schema_overhead_tokens in RunMetrics
- `uv run pytest tests/core/test_models.py -q`

After Phase 6:
- `uv run python main.py --dry-run` — all 21 configs load without error

Final gate:
- `uv run pytest tests/ -q` — all tests pass
- `uv run python main.py --dry-run` — exits cleanly

================================================================================
## FILES SUMMARY
================================================================================

CREATE:
- src/features/stats.py  (Phase 4)

MODIFY:
- src/core/models.py  (Phase 3: add 3 validity flags; Phase 5: add 2 metric fields)
- src/features/agent_integration/agno_runner.py  (Phase 3: compute flags; Phase 5: compute net_spt)
- src/features/llm_judge.py  (Phase 3: accept JudgeConfig, use gpt-5.1-mini default)
- src/orchestrator/benchmark.py  (Phase 3: compute parametric_success after retrieval; wire judge config)
- src/features/multi_run.py  (Phase 4: validity gate + CI stats)
- main.py  (Phase 4: --runs default=5, end-of-run status summary)
- configs/tools.yaml  (Phase 6: symmetric prompts for all 21 configs)

DO NOT TOUCH (already done):
- src/core/scoring.py
- src/core/provider_factory.py
- configs/tasks/aging_stale.yaml
- configs/provider.yaml
- README.md
