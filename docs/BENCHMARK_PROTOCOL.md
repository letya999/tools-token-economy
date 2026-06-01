# Benchmark Protocol

## Purpose

Measure which **retrieval tools** allow an LLM agent to solve Python coding tasks while
consuming the fewest tokens - while maintaining task quality. The benchmark ranks TOOLS,
not models or tasks. Model and codebase are held constant within a run; only the tool
configuration varies.

## Scope limitations

Results are valid for: *"on Python codebase X, with model Y, tool config Z consumes
N% fewer tokens than config W while achieving comparable task quality."*

External validity (generalising across codebases/task types) requires running the full
multi-task matrix and observing consistent Friedman/Nemenyi winners.

---

## Running modes (cheapest to most expensive)

### 1. Smoke run - zero cost, pipeline check

```bash
# Dry run - no real API calls, validates config loading and worktrees
python main.py --dry-run --runs 1

# Single config, one real run (~$0.01-0.04)
python main.py --runs 1 --config-ids 02_claude_code_like
```

No statistical weight. Use to confirm the pipeline works end-to-end.

### 2. Per-task internal significance - one task, one model

```bash
# All 21 configs, 6 runs each (~$2-5 depending on model)
python main.py --runs 6

# Subset of configs
python main.py --runs 6 --config-ids 09_rg 14_repo_map 16_serena_only
```

Output: per-config bootstrap 90% CI on `net_spt`, validity status per config.

**Interpreting results:**
- Status `OK`: n_valid >= 4, CV < 0.5. Use for ranking.
- Status `LOW_CONFIDENCE`: n_valid = 3 or borderline CV. Use with caution.
- Status `UNSTABLE` (CV > 0.5) or `INSUFFICIENT_DATA` (n_valid <= 2): excluded from
  ranking table. Re-run with `--retry-failed` or add `--runs`.
- **Configs with overlapping 90% CI are statistically indistinguishable.** Do not claim
  "tool X is N times better than Y" without non-overlapping CIs.

### 3. Task sweep - external validity for one model

```bash
# Estimate cost first
python main.py --estimate --task-suite configs/task_suites/python_core_v1.yaml --runs 6

# Run (all 10 tasks x 21 configs x 6 runs on one model)
python main.py --task-suite configs/task_suites/python_core_v1.yaml --runs 6
```

Output: per-task bootstrap CI + cross-task **Friedman test** + **Nemenyi CD groups**.

**Interpreting cross-task results:**
- Friedman p < 0.05: the tool configurations are NOT equivalent across tasks.
- Nemenyi Critical Difference (CD): configs within CD of each other form a
  statistically indistinguishable group (tie-band). Only configs separated by > CD
  from all others in the best group are declared "consistent winners".
- `consistent_winners`: top-ranked configs on EVERY task in the suite.

### 4. Full matrix - 4 models x 10 tasks x 21 configs x 6 runs

```bash
# Always estimate first!
python main.py --estimate --matrix \
  --task-suite configs/task_suites/python_core_v1.yaml \
  --models configs/model_sweep.yaml \
  --runs 6

# Run (requires --yes to skip confirmation; ~$100 at default model mix)
python main.py --matrix \
  --task-suite configs/task_suites/python_core_v1.yaml \
  --models configs/model_sweep.yaml \
  --runs 6 --yes
```

Output: cross-task Friedman per model + **cross-model Spearman rank correlation**.

**Interpreting cross-model stability:**
- High rank correlation (rho > 0.8 across all model pairs): the tool ranking is
  model-agnostic. The result generalises beyond the specific agent model.
- `stable_winners`: configs that rank #1 (or tied for #1) in EVERY model's
  Nemenyi top group. These are the most robust recommendations.

---

## Budget safety

Default limits (in `configs/budget.yaml`, overridable via CLI):

| Limit | Default | CLI override |
|---|---|---|
| Per-config run | $0.40 | `--max-config-usd` |
| Per-session (1 model x 1 task, all configs x N runs) | $8.00 | `--max-session-usd` |
| Full matrix | $50.00 | `--max-matrix-usd` |
| Tokens per config run | 600K | `--max-tokens-per-config` |

The `agent_runaway` flag fires (and the run is excluded from aggregation) when:
- `token_exceeded` (> max_tokens_per_config), OR
- `tool_errors > 10`, OR
- `agent_cycles > 40`

**Always run `--estimate` before any paid matrix run** and confirm the projected
USD is below `max_matrix_usd`.

---

## Primary metric: net_spt

`net_spt` is the headline token-economy metric:

```
net_spt = (task_solved_score * 1000) / max(total_tokens - schema_overhead_tokens, 1)
```

- `task_solved_score`: graded 0-1 from the LLM judge (not binary success).
- `schema_overhead_tokens`: estimated tokens consumed by tool schema definitions
  (resent each call), computed as `tool_schema_bytes / 4 * model_calls`.
- Dividing by **reasoning tokens** (total minus schema overhead) makes the comparison
  fair between lightweight tools (small schemas) and rich semantic tools (e.g. Serena,
  which carry large MCP schemas).

`success_per_token` (per 1M total tokens) is the secondary metric for raw comparison.

---

## Statistical interpretation quick-reference

| Scenario | Claim allowed |
|---|---|
| n=1 run | Point estimate only. No significance claim. |
| n>=5, status=OK, non-overlapping CI | "Config X has significantly higher net_spt than Y (90% CI)." |
| n>=5, overlapping CI | "Configs X and Y are statistically indistinguishable." |
| Friedman p<0.05, separated by >CD | "Tool X is a consistent winner across N task types." |
| Friedman p>=0.05 | "No tool is significantly better across these tasks." |
| High cross-model rho (>0.8) | "The ranking is robust across agent models." |

---

## Adding tasks and suites

See [docs/TASK_AUTHORING.md](TASK_AUTHORING.md) for the task authoring guide,
the memory-proof rule, and the category taxonomy.
