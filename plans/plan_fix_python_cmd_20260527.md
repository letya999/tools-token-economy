# Fix: Replace 'python' with sys.executable in _setup_target_repo

## Problem
`benchmark.py:_setup_target_repo` calls `subprocess.run(["python", ...])` on line 106.
In WSL Ubuntu, only `python3` exists — no `python` symlink. This crashes the real benchmark
immediately after preflight passes.

## File to modify
`src/orchestrator/benchmark.py`

## Change
Add `import sys` at the top if not already present (it already is on line 7).
On line 106, replace:
```python
["python", "-m", "py_compile", str(f)],
```
with:
```python
[sys.executable, "-m", "py_compile", str(f)],
```

Using `sys.executable` is the correct fix: it always points to the exact Python interpreter
running the benchmark (`.venv-wsl/bin/python3.13`), works on all platforms (Windows, WSL,
Linux), and avoids dependency on PATH having a `python` symlink.

## No other changes needed
`sys` is already imported at line 7 of benchmark.py. No new imports required.
