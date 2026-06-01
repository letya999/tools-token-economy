# Backlog Implementation Plan: P0 + P1 Items

**Date**: 2026-05-27  
**Scope**: BACKLOG.md items #1 (P0), #2 (P1), #4 (P1), #8 (P1)  
**Working dir**: `C:\Users\User\a_projects\tools_token_economy`  
**Run all commands via WSL**: `wsl bash -c "cd /mnt/c/Users/User/a_projects/tools_token_economy && ..."`

---

## Item #1 (P0): Eliminate env_error — Replace Worktree Isolation

### Problem
`GitIsolationProvider` creates git worktrees on NTFS (`/mnt/c/...`). `uv` and `pytest` are
not in PATH inside WSL subprocesses spawned for these worktrees, so `ExecutionValidator`
always returns `env_error`.

### Root cause
`ExecutionValidator._run_cmd` sets `UV_PROJECT_ENVIRONMENT` correctly, but `uv` binary itself
is missing from the subprocess PATH when the CWD is an NTFS worktree.

### Solution: Remove git worktree isolation; patch directly on the target repo

Replace the "create worktree → agent writes there → run tests → remove worktree" loop with:
1. Agent writes changes directly to a **temp copy** of the target repo (simple `shutil.copytree`)
2. Tests run inside the temp copy (on Linux `/tmp/` filesystem, not NTFS)
3. Temp copy is deleted after the run

This avoids ALL PATH/NTFS issues because the temp copy lives on the Linux native fs.

### Files to modify

#### `src/features/isolation.py`
- Add a new class `DirectCopyIsolationProvider` alongside `GitIsolationProvider`
- `setup(run_id)`: 
  - Creates `/tmp/benchmark_runs/{run_id}/` (Linux native fs in WSL)
  - Does `shutil.copytree(self.repo_path, tmp_path, symlinks=True, ignore_dangling_symlinks=True)`
  - Returns `tmp_path`
- `teardown(run_id)`:
  - Does `shutil.rmtree(tmp_path, ignore_errors=True)`
- Keep `GitIsolationProvider` as-is for compatibility

#### `src/orchestrator/benchmark.py`
- In `BenchmarkOrchestrator.__init__`: detect platform and choose provider
  - If `sys.platform != "win32"` and repo_path starts with `/mnt/`: use `DirectCopyIsolationProvider`
  - Otherwise: keep `GitIsolationProvider`
  - New logic: `self.isolation = _make_isolation_provider(self.repo_path, self.worktree_base)`
- Add helper `_make_isolation_provider(repo_path, worktree_base)` that returns the right provider
- The worktree_base for `DirectCopyIsolationProvider` should be `/tmp/benchmark_runs`

#### `src/core/models.py`
- No changes needed

### Test validation
After implementation, run a single config and verify `execution_result` is `passed` or `failed`,
NOT `env_error`. Use config `02_claude_code_like` as the test case.

---

## Item #2 (P1): Fix 13_lsp — Add Explicit Navigation Guidance

### Problem
Config `13_lsp` has `lsp_symbols` + `read` tools but agent still makes zero file changes.
The LSP tool returns symbol definitions but doesn't guide the agent to the exact file path
containing the target function.

### Root cause
`lsp_symbols` returns results like `{"symbol": "...", "file": "...", "line": N}` but the
tool restriction prefix for `13_lsp` doesn't explain HOW to translate LSP output into a
`read` call on the correct file.

### Solution: Improve the tool restriction prefix for lsp archetype

#### `src/features/prompt_builder.py`
Locate `build_tool_restriction_prefix` function. Add a specific section for configs that
include `lsp_symbols`:

```python
if "lsp_symbols" in tools:
    prefix += (
        "\n\nIMPORTANT - HOW TO USE lsp_symbols:\n"
        "1. Call lsp_symbols with the name of the function/class you want to find.\n"
        "2. The result will include a 'file' field with the exact file path.\n"
        "3. Use that file path with the 'read' tool to read the file content.\n"
        "4. Then make your changes with 'write' or 'patch' on that file path.\n"
        "Do NOT just return information — you MUST write/patch the file."
    )
```

Also inspect `src/features/tool_registry/tools/lsp_symbols/__init__.py` and its validator.
Ensure the tool output format actually includes a `file` field. If it returns just symbol
names without file paths, fix the output format to always include `{"symbol": str, "file": str, "line": int}`.

#### `src/features/tool_registry/tools/lsp_symbols/__init__.py`
- Inspect what `execute()` currently returns
- If it does NOT include file paths in output, update it to include them
- Format should be: `"Found symbol 'X' in file/path/to/file.py at line N"`

---

## Item #4 (P1): Expand Evaluation Metrics — 4 New Judge Scores

### Problem
Only 3 judge scores exist: `task_solved_score`, `tool_correctness_score`, `context_quality_score`.
BACKLOG requests 4 more: `correctness_score`, `minimality_score`, `pattern_adherence_score`,
`tool_sequence_score`.

### Files to modify

#### `src/features/llm_judge.py`

**Step 1 — Extend `JudgeReport` model** (add 4 new fields):
```python
class JudgeReport(BaseModel):
    # existing fields...
    correctness_score: float = 0.0
    correctness_reasoning: str = ""
    minimality_score: float = 0.0
    minimality_reasoning: str = ""
    pattern_adherence_score: float = 0.0
    pattern_adherence_reasoning: str = ""
    tool_sequence_score: float = 0.0
    tool_sequence_reasoning: str = ""
```

**Step 2 — Add 4 new `_SYSTEM` prompt class attributes** to `LLMJudge`:

```python
_CORRECTNESS_SYSTEM = (
    "You are an objective evaluator for a software engineering benchmark.\n"
    "You will be shown: a task description, and the git diff of changes made by an AI agent.\n"
    'Return ONLY a JSON object: {"score": float, "reasoning": "1-2 sentences"}\n\n'
    "Score 1.0 = code is syntactically and semantically correct, would pass code review.\n"
    "Score 0.5 = mostly correct but has a subtle bug, wrong type, or edge case missing.\n"
    "Score 0.0 = syntax error, wrong function signature, or logically broken.\n"
    "If no code changes were made, score MUST be 0.0."
)

_MINIMALITY_SYSTEM = (
    "You are an objective evaluator for a software engineering benchmark.\n"
    "You will be shown: a task description, and the git diff of changes made by an AI agent.\n"
    'Return ONLY a JSON object: {"score": float, "reasoning": "1-2 sentences"}\n\n'
    "Score 1.0 = agent made exactly the required changes, touched no unrelated code.\n"
    "Score 0.5 = required changes made but also modified unrelated files or added extras.\n"
    "Score 0.0 = massive unnecessary changes, refactored unrelated code, or touched wrong files.\n"
    "If no code changes were made, score MUST be 0.0."
)

_PATTERN_ADHERENCE_SYSTEM = (
    "You are an objective evaluator for a software engineering benchmark.\n"
    "You will be shown: a task description, and the git diff of changes made by an AI agent.\n"
    'Return ONLY a JSON object: {"score": float, "reasoning": "1-2 sentences"}\n\n'
    "Score 1.0 = agent followed existing code patterns: naming, style, test structure, imports.\n"
    "Score 0.5 = mostly consistent but has minor style deviation from surrounding code.\n"
    "Score 0.0 = introduced completely different style, naming, or structure than surrounding code.\n"
    "If no code changes were made, score MUST be 0.0."
)

_TOOL_SEQUENCE_SYSTEM = (
    "You are an objective evaluator for a software engineering benchmark.\n"
    "You will be shown: the sequence of ALL tool calls (retrieval + write) an AI agent made.\n"
    'Return ONLY a JSON object: {"score": float, "reasoning": "1-2 sentences"}\n\n'
    "Score 1.0 = logical order: search → read target file → write. No redundant reads.\n"
    "Score 0.5 = some redundancy (re-read same file, searched after already found target).\n"
    "Score 0.0 = chaotic order, wrote without reading, or made >5 redundant search calls.\n"
    "If no tool calls were made, score MUST be 0.0."
)
```

**Step 3 — Add 4 new private judge methods** to `LLMJudge`:
- `_judge_correctness(task_description, patch) -> tuple[float, str]`
- `_judge_minimality(task_description, patch) -> tuple[float, str]`
- `_judge_pattern_adherence(task_description, patch) -> tuple[float, str]`
- `_judge_tool_sequence(agent_messages) -> tuple[float, str]`

Each follows the same pattern as existing `_judge_task_solved`: call `self.client.chat.completions.create`,
parse JSON response, return `(float, str)`.

**Step 4 — Update `evaluate()` method** to call all 4 new methods and populate JudgeReport.

#### `src/core/models.py`

Extend `RunMetrics` with 4 new fields (after existing judge fields):
```python
correctness_score: float = 0.0
minimality_score: float = 0.0
pattern_adherence_score: float = 0.0
tool_sequence_score: float = 0.0
judge_reasoning_correctness: str = ""
judge_reasoning_minimality: str = ""
judge_reasoning_pattern: str = ""
judge_reasoning_tool_sequence: str = ""
```

#### `src/orchestrator/benchmark.py`

In the method that populates `RunMetrics` from `JudgeReport`, add the 4 new field mappings:
```python
correctness_score=judge.correctness_score,
minimality_score=judge.minimality_score,
pattern_adherence_score=judge.pattern_adherence_score,
tool_sequence_score=judge.tool_sequence_score,
judge_reasoning_correctness=judge.correctness_reasoning,
judge_reasoning_minimality=judge.minimality_reasoning,
judge_reasoning_pattern=judge.pattern_adherence_reasoning,
judge_reasoning_tool_sequence=judge.tool_sequence_reasoning,
```

Find the exact location by searching for `judge_reasoning_task` in `benchmark.py` — the new
fields go directly after it.

---

## Item #8 (P1): Target Repo Preflight — Verify Target File + Baseline Test Count

### Problem
Preflight doesn't verify that the specific file the benchmark task targets actually exists,
and doesn't measure baseline test count for the specific test file being modified.

### Files to modify

#### `src/core/models.py`

Add optional fields to `BenchmarkMeta`:
```python
target_file: str | None = None      # e.g. "tests/unit/test_api_google_oauth.py"
target_test: str | None = None      # e.g. "tests/unit/test_api_google_oauth.py"
required_files: list[str] = []      # for retrieval_recall metric (item #4b)
```

#### `configs/benchmark_configs.yaml`

Add to the `benchmark:` section:
```yaml
benchmark:
  repo: "..."
  test_cmd: "..."
  target_file: "tests/unit/test_api_google_oauth.py"
  target_test: "tests/unit/test_api_google_oauth.py"
  required_files:
    - "tests/unit/test_api_google_oauth.py"
    - "src/api/google_oauth.py"
```

#### `src/features/preflight.py`

In `PreflightChecker.__init__`, add `target_file: str | None = None` and `target_test: str | None = None` parameters.

Add a new check method `_check_target_file_and_baseline()`:

```python
def _check_target_file_and_baseline(self) -> list[PreflightResult]:
    results = []
    
    # Check target_file exists
    if self.target_file:
        full_path = os.path.join(self.repo_path, self.target_file)
        exists = os.path.isfile(full_path)
        results.append(PreflightResult(
            name=f"Target file exists: {self.target_file}",
            passed=exists,
            level="critical",
            detail=full_path if exists else f"NOT FOUND: {full_path}",
        ))
        if not exists:
            return results
    
    # Run baseline test count on specific test file
    if self.target_test and shutil.which("uv"):
        test_file_path = os.path.join(self.repo_path, self.target_test)
        if os.path.isfile(test_file_path):
            cmd = f"uv run --extra dev pytest {self.target_test} -q --no-header"
            try:
                proc = subprocess.run(
                    cmd, shell=True, cwd=self.repo_path,
                    capture_output=True, text=True, timeout=60
                )
                output = proc.stdout + proc.stderr
                pass_match = re.search(r"(\d+) passed", output)
                baseline_count = int(pass_match.group(1)) if pass_match else 0
                passed = baseline_count > 0
                results.append(PreflightResult(
                    name=f"Baseline tests in {self.target_test}",
                    passed=passed,
                    level="critical" if not passed else "info",
                    detail=f"Baseline: {baseline_count} tests pass" + ("" if passed else " — 0 baseline tests, check target file"),
                ))
            except Exception as e:
                results.append(PreflightResult(
                    name=f"Baseline tests in {self.target_test}",
                    passed=False,
                    level="warning",
                    detail=f"Could not run baseline: {e}",
                ))
    
    return results
```

Also add `import re` at the top of `preflight.py` if not already present.

In `PreflightChecker.run()`, add `self._check_target_file_and_baseline` to the `for check in [...]` list.

#### `src/orchestrator/benchmark.py`

Update `_run_preflight()` to pass `target_file` and `target_test` from `self.meta`:
```python
checker = PreflightChecker(
    repo_path=self.repo_path,
    configs=self.configs,
    test_cmd=self.test_cmd,
    dry_run=self.dry_run,
    selected_ids=selected_ids,
    target_file=self.meta.target_file if self.meta else None,
    target_test=self.meta.target_test if self.meta else None,
)
```

---

## Execution Order

Implement in this order (each item is independent, but this order reduces rework):

1. **Item #8 first** — adds `target_file`/`target_test` to `BenchmarkMeta` and preflight.
   Touches: `models.py`, `preflight.py`, `benchmark.py`, `benchmark_configs.yaml`

2. **Item #4 second** — extends `JudgeReport` and `RunMetrics` with 4 new scores.
   Touches: `llm_judge.py`, `models.py`, `benchmark.py`

3. **Item #2 third** — fix LSP tool output and prompt builder.
   Touches: `prompt_builder.py`, `src/features/tool_registry/tools/lsp_symbols/__init__.py`

4. **Item #1 last** — replace worktree isolation with direct copy.
   Touches: `isolation.py`, `benchmark.py`

---

## Tests to run after implementation

```bash
# Run full unit test suite
wsl bash -c "cd /mnt/c/Users/User/a_projects/tools_token_economy && uv run pytest tests/ -q"

# Verify new judge fields are populated (dry run)
wsl bash -c "cd /mnt/c/Users/User/a_projects/tools_token_economy && uv run python main.py --dry-run --config 02_claude_code_like"
```

Expected: all existing 133 unit tests still pass; dry run shows new score fields in output JSON.

---

## Notes for implementer

- The `benchmark.py` method that writes judge scores to `RunMetrics` is NOT in the read excerpt
  above. Search for `judge_reasoning_task` in `benchmark.py` to find the exact location.
- `preflight.py` already imports `re` via subprocess — check before adding duplicate import.
- `DirectCopyIsolationProvider.setup()` must handle the case where `/tmp/benchmark_runs/`
  doesn't exist by calling `os.makedirs(parent, exist_ok=True)` before copytree.
- Keep `GitIsolationProvider` class in `isolation.py` — don't delete it, just add new class.
- The `evaluate()` method in `LLMJudge` makes 3 API calls currently. Adding 4 more = 7 total.
  This is acceptable for a benchmark tool. Consider adding a `detailed=True` parameter to
  `evaluate()` that gates the new 4 calls, defaulting to `True`.
