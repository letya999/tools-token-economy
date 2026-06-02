# Benchmark Results Summary

## Hard task: aging_stale (2026-06-01, session 20260601_131317)
- 21 configs × 6 reps = 126 runs, task=hard (add is_stale flag, Polars, 3 files)
- Total agent cost: $15.16, judge: gpt-5.4-nano
- Token efficiency champion: 16_serena_only (100% pass, 79K avg tokens, judge=0.68)
- Quality champion: 04_codex_like (100% pass, judge=0.85, 861K tokens — 10x more expensive)
- Best balance: 20_serena_semble (83% pass, judge=0.79, 120K tokens)
- Complete failure: 03_gemini_like (0% pass, judge=0.00, 419K tokens — context explosion)

## Medium task: Bearer token bug (2026-05-25, session 20260525_002838)
- 20 configs, 1 rep, 14/20 passed (70%)
- Efficiency winner: 10_ugrep (2,697 tokens, $0.0018)
- Note: serena_only failed this session due to config issue (fixed later)

## Key Findings
- Task complexity is the key differentiator:
  - Medium: lightweight grep tools (ugrep/grep) are most efficient
  - Hard: semantic tools (serena) dominate — they navigate multi-file dependencies better
- pass_rate != quality: rg_lsp, git_grep had 67% pass but judge=0.37 (shallow implementation)
- Zero judge without zero pass: rg_repo_map (0% pass, judge=0.49) — correct approach, execution failure
- gemini_like (read_all+repo_map) consistently worst on BOTH task types — context explosion
