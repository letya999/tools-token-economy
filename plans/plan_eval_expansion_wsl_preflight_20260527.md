# Plan: Eval Expansion + WSL Pre-flight + Target Repo Setup

**Created:** 2026-05-27  
**Priority:** High  
**Context:** After run_20260526_213013 revealed 3 infrastructure bugs and missing eval dimensions.

---

## Objective

1. Expand LLM judge from 2 to 3 dimensions (add `context_quality`)
2. Fix `_is_env_error()` to check stdout for ModuleNotFoundError
3. WSL setup: ensure LSP (jedi), semble, tree-sitter are installed + verified
4. Pre-run target repo setup: `uv sync` + importability check before benchmark starts
5. Baseline guard: abort if baseline = 0 tests

---

## Changes Required

### A. `src/core/models.py`

Add to `RunMetrics`:
```python
context_quality_score: float = 0.0
judge_reasoning_context: str = ""
```

Add to `JudgeReport` in `llm_judge.py`:
```python
context_quality_score: float = 0.0
context_quality_reasoning: str = ""
```

### B. `src/features/llm_judge.py`

Add third judge dimension `_judge_context_quality()`:

System prompt for context judge:
```
You are an objective evaluator for a software engineering benchmark.
You will be shown: the task description, and the complete list of file-reading
and search tool calls the agent made (filenames + queries only, not content).
Return ONLY a JSON object: {"score": float, "reasoning": "1-2 sentences"}

Scoring rubric (use fuzzy values 0.0/0.25/0.5/0.75/1.0):
1.0 = Agent found exactly the right files/symbols with minimum reads. No irrelevant files.
0.75 = Good retrieval with at most 1 redundant read or 1 missed helper file.
0.5 = Found the target but with >2 irrelevant reads OR missed an important fixture/helper.
0.25 = Read some files but missed the primary source being tested.
0.0 = No reads, or all reads irrelevant, or agent hallucinated without reading codebase.

Note: Count only read/search calls (not write/patch/shell). Fewer focused reads = better.
```

User prompt: task description + list of (tool_name, filename_or_query) tuples from agent_messages.

Wire into `evaluate()` and populate `context_quality_score` / `context_quality_reasoning` in `JudgeReport`.

### C. `src/features/execution_validator.py`

In `_is_env_error()`, add stdout check for import errors specifically:
```python
_ENV_ERROR_PATTERNS_STDOUT = [
    r"ModuleNotFoundError",
    r"No module named",
    r"ImportError",
]

def _is_env_error(self, stdout, stderr, exit_code):
    if exit_code in _ENV_ERROR_EXIT_CODES:
        return True
    if any(re.search(p, stderr) for p in _ENV_ERROR_PATTERNS):
        return True
    # Pytest collection errors appear in stdout — check specifically for import failures
    if any(re.search(p, stdout) for p in _ENV_ERROR_PATTERNS_STDOUT):
        return True
    return False
```

### D. `scripts/setup_tools/setup_ast_lsp.sh`

Replace current minimal script with a full install+verify:

```bash
#!/bin/bash
set -e
VENV="/mnt/c/Users/User/a_projects/tools_token_economy/.venv-wsl"
PY="$VENV/bin/python"

echo "=== Tree-sitter Python bindings ==="
$PY -c "import tree_sitter" 2>/dev/null || $VENV/bin/pip install tree-sitter
# Build Python grammar
if [ ! -f "$VENV/lib/python3.13/site-packages/tree_sitter_python" ]; then
    $VENV/bin/pip install tree-sitter-python
fi
$PY -c "from tree_sitter_languages import get_language; get_language('python'); print('[OK] tree-sitter python grammar')" \
  || { echo '[FAIL] tree-sitter-languages not available'; exit 1; }

echo "=== LSP (jedi) ==="
$PY -c "import jedi; print('[OK] jedi', jedi.__version__)"
# Smoke test against a real Python file
$PY -c "
import jedi
script = jedi.Script('import os\nos.path.')
completions = script.complete(2, 9)
assert len(completions) > 0, 'jedi returned no completions'
print('[OK] jedi completions working:', len(completions), 'results')
"

echo "=== AST grep ==="
which ast-grep || { echo '[FAIL] ast-grep not in PATH'; exit 1; }
ast-grep --version && echo '[OK] ast-grep'

echo "AST and LSP setup complete."
```

### E. `scripts/setup_tools/setup_serena_semble.sh`

Add semble pre-warm section:
```bash
echo "=== Semble pre-warm ==="
# Pre-download semble package so first benchmark run doesn't time out
if ! uvx --from semble semble --version &>/dev/null 2>&1; then
    echo "Downloading semble via uvx (first-time install)..."
    uv tool install semble || uvx --from semble semble --help || true
fi
# Mark warmup done
touch ~/.semble_warmed_up
uvx --from semble semble --version 2>/dev/null && echo "[OK] semble ready" || echo "[WARN] semble not verified"
```

### F. `main.py` (or `src/features/benchmark_runner.py`)

Add `_setup_target_repo()` method called BEFORE baseline measurement:

```python
def _setup_target_repo(self, repo_path: str, test_cmd: str) -> None:
    """Ensure target repo is installed and importable before benchmark starts."""
    log.info("Running `uv sync --extra dev` in target repo: %s", repo_path)
    result = subprocess.run(
        ["uv", "sync", "--extra", "dev"],
        cwd=repo_path, capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Target repo uv sync failed:\n{result.stderr[:2000]}\n"
            "Fix the target repo before running the benchmark."
        )

    # Verify Python can at least parse key modules (import errors from missing
    # env vars are acceptable; syntax errors and missing packages are not)
    py_files = list(Path(repo_path).glob("**/*.py"))[:20]  # spot check
    for f in py_files:
        r = subprocess.run(
            ["python", "-m", "py_compile", str(f)],
            cwd=repo_path, capture_output=True, text=True
        )
        if r.returncode != 0 and "SyntaxError" in r.stderr:
            raise RuntimeError(f"Syntax error in target repo {f}:\n{r.stderr}")
    log.info("Target repo setup verified OK.")
```

Add baseline guard after `measure_test_baseline()`:
```python
baseline = self.validator.measure_test_baseline(test_cmd)
if baseline == 0:
    raise RuntimeError(
        "Baseline measurement returned 0 passing tests. "
        "Target repo may be misconfigured. Run `uv sync --extra dev` in target repo and retry."
    )
log.info("Baseline: %d tests passing.", baseline)
```

---

## File Summary

| File | Change Type | Priority |
|------|------------|---------|
| `src/core/models.py` | Add field `context_quality_score`, `judge_reasoning_context` | High |
| `src/features/llm_judge.py` | Add `_judge_context_quality()`, wire to `evaluate()` | High |
| `src/features/execution_validator.py` | Add stdout check in `_is_env_error()` | Medium |
| `scripts/setup_tools/setup_ast_lsp.sh` | Full install+verify for tree-sitter, jedi, ast-grep | High |
| `scripts/setup_tools/setup_serena_semble.sh` | Add semble pre-warm | High |
| `main.py` or `benchmark_runner.py` | Add `_setup_target_repo()` + baseline guard | High |

---

## Test Requirements

After implementation:
- `pytest tests/features/test_llm_judge.py` — must pass with mocked 3-dimension response
- `pytest tests/core/test_models.py` — must pass with new fields
- `pytest tests/features/test_execution_validator.py` — must pass with stdout `_is_env_error` check
- `bash scripts/setup_tools/setup_ast_lsp.sh` — must complete without error in WSL
- `bash scripts/setup_tools/setup_serena_semble.sh` — must complete, semble pre-warmed
- Dry-run: `python main.py --dry-run` — must show baseline > 0 in log
