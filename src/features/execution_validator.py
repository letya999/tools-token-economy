"""
Universal execution validator for benchmark runs.

Does NOT assume the task involves tests. Can validate any coding task.
Returns one of: "passed" | "failed" | "env_error" | "not_verified"

Priority:
1. validation_cmd (if specified in BenchmarkMeta) вЂ” most specific
2. test_cmd + test files changed + baseline comparison вЂ” for test-writing tasks
3. python -m py_compile on changed .py files вЂ” syntax check fallback
4. not_verified вЂ” judge decides
"""
import logging
import os
import re
import subprocess
from dataclasses import dataclass

_log = logging.getLogger(__name__)

# Exit codes / stderr patterns that indicate environment failure (not agent failure)
_ENV_ERROR_PATTERNS = [
    r"ModuleNotFoundError",
    r"No module named",
    r"command not found",
    r"No such file or directory",
    r"Connection refused",
    r"ECONNREFUSED",
    r"address already in use",
    r"Permission denied",
    r"Cannot connect",
    r"uvicorn",  # server start issues
]

_ENV_ERROR_EXIT_CODES = {126, 127}


@dataclass
class ExecutionResult:
    outcome: str  # "passed" | "failed" | "env_error" | "not_verified"
    tests_passed: int = 0
    tests_failed: int = 0
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    method_used: str = ""  # "validation_cmd" | "test_cmd" | "syntax_check" | "none"


class ExecutionValidator:
    """
    Universal execution validator. Works regardless of task type or whether     
    the target project has tests.
    """

    def __init__(self, worktree_path: str, run_dir: str | None = None):
        self.worktree_path = worktree_path
        self.run_dir = run_dir

    def validate(
        self,
        validation_cmd: str | None,
        test_cmd: str | None,
        baseline_pass_count: int | None,
        eval_env: dict | None = None,
    ) -> ExecutionResult:
        """
        Run validation. Returns ExecutionResult.
        """
        # Check if agent made any changes at all
        changed_files = self._get_changed_files()
        if not changed_files:
            return ExecutionResult(outcome="not_verified", method_used="none")  

        # Priority 1: explicit validation_cmd
        if validation_cmd:
            return self._run_cmd(validation_cmd, method="validation_cmd", eval_env=eval_env)

        # Priority 2: test_cmd with baseline comparison
        if test_cmd:
            test_files = [f for f in changed_files if self._is_test_file(f)]    
            if test_files or baseline_pass_count is not None:
                return self._run_test_cmd(test_cmd, baseline_pass_count, eval_env=eval_env)

        # Priority 3: syntax check on changed Python files
        py_files = [f for f in changed_files if f.endswith(".py")]
        if py_files:
            return self._syntax_check(py_files)

        return ExecutionResult(outcome="not_verified", method_used="none")      

    def _get_changed_files(self) -> list[str]:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.worktree_path, capture_output=True, text=True, timeout=10  
        )
        files = []
        for line in result.stdout.splitlines():
            if len(line) < 3:
                continue
            fname = line[3:].strip()
            if " -> " in fname:
                fname = fname.split(" -> ", 1)[1]
            files.append(fname)
        return files

    def _is_test_file(self, path: str) -> bool:
        base = os.path.basename(path)
        return (
            path.startswith("tests/") or
            base.startswith("test_") or
            base.endswith("_test.py")
        )

    def _is_env_error(self, stdout: str, stderr: str, exit_code: int) -> bool:  
        if exit_code in _ENV_ERROR_EXIT_CODES:
            return True
        combined = stdout + stderr
        return any(re.search(p, combined) for p in _ENV_ERROR_PATTERNS)

    def _parse_pytest_counts(self, output: str) -> tuple[int, int]:
        passed = failed = 0
        # Look for "X passed, Y failed" in pytest output
        pass_match = re.search(r"(\d+) passed", output)
        fail_match = re.search(r"(\d+) failed", output)
        error_match = re.search(r"(\d+) error", output)
        
        if pass_match:
            passed = int(pass_match.group(1))
        if fail_match:
            failed = int(fail_match.group(1))
        if error_match:
            failed += int(error_match.group(1))
            
        return passed, failed

    def _run_cmd(self, cmd: str, method: str, eval_env: dict | None = None) -> ExecutionResult:
        env = os.environ.copy()
        if eval_env:
            env.update(eval_env)
        
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=self.worktree_path,
                capture_output=True, text=True, timeout=60, env=env
            )
            stdout, stderr = proc.stdout, proc.stderr
            exit_code = proc.returncode

            if exit_code == 0:
                return ExecutionResult(outcome="passed", method_used=method, stdout=stdout, stderr=stderr)
            
            if self._is_env_error(stdout, stderr, exit_code):
                return ExecutionResult(outcome="env_error", method_used=method, stdout=stdout, stderr=stderr, exit_code=exit_code)
            
            return ExecutionResult(outcome="failed", method_used=method, stdout=stdout, stderr=stderr, exit_code=exit_code)
        except subprocess.TimeoutExpired:
            return ExecutionResult(outcome="failed", method_used=method, stderr="Validation timed out (60s)")
        except Exception as e:
            return ExecutionResult(outcome="env_error", method_used=method, stderr=str(e))

    def _run_test_cmd(self, test_cmd: str, baseline_pass_count: int | None, eval_env: dict | None = None) -> ExecutionResult:
        res = self._run_cmd(test_cmd, method="test_cmd", eval_env=eval_env)
        if res.outcome == "env_error":
            return res
        
        passed, failed = self._parse_pytest_counts(res.stdout + res.stderr)
        res.tests_passed = passed
        res.tests_failed = failed

        if baseline_pass_count is not None:
            # We have a baseline! Success means we didn't regress AND potentially improved.
            # If failed > 0, it's a failure.
            if failed > 0:
                res.outcome = "failed"
            elif passed >= baseline_pass_count:
                res.outcome = "passed"
            else:
                # This is weird вЂ” fewer tests passed than baseline but none failed.
                # Could happen if some tests were deleted.
                res.outcome = "failed"
        else:
            # No baseline. Standard pass/fail.
            if res.exit_code == 0:
                res.outcome = "passed"
            else:
                res.outcome = "failed"
        
        return res

    def _syntax_check(self, py_files: list[str]) -> ExecutionResult:
        errors = []
        for f in py_files:
            try:
                subprocess.run(
                    ["python", "-m", "py_compile", f],
                    cwd=self.worktree_path, capture_output=True, text=True, check=True
                )
            except subprocess.CalledProcessError as e:
                errors.append(f"{f}: {e.stderr.strip()}")
        
        if not errors:
            # Syntax is OK, but we don't know if it actually works.
            return ExecutionResult(outcome="not_verified", method_used="syntax_check")
        
        return ExecutionResult(
            outcome="failed", method_used="syntax_check",
            stderr="\n".join(errors)
        )
