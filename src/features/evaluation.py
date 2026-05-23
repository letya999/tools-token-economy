import re
from typing import Optional
from dataclasses import dataclass, field
from src.features.shell import ShellExecutor

@dataclass
class EvalOutcome:
    success: bool
    eval_score: float
    output: str
    tests_passed: int = 0
    tests_failed: int = 0
    tests_total: int = 0
    patch: Optional[str] = None

class EvalEngine:
    """
    Runs tests and evaluates the result of task execution.
    Parses pytest output to extract pass/fail counts.
    """
    # Matches: "5 passed", "3 passed, 1 failed", "2 failed", "4 passed, 2 warnings"
    _PYTEST_SUMMARY = re.compile(
        r'(\d+) passed|(\d+) failed|(\d+) error',
        re.IGNORECASE,
    )

    def __init__(self, shell: Optional[ShellExecutor] = None):
        self.shell = shell or ShellExecutor()

    def _parse_pytest_counts(self, output: str) -> tuple[int, int]:
        """Return (passed, failed) extracted from pytest summary line."""
        passed = 0
        failed = 0
        for match in self._PYTEST_SUMMARY.finditer(output):
            if match.group(1):
                passed = int(match.group(1))
            elif match.group(2):
                failed += int(match.group(2))
            elif match.group(3):
                failed += int(match.group(3))
        return passed, failed

    def evaluate(self, worktree_path: str, test_cmd: str) -> EvalOutcome:
        """
        Runs the test command and returns outcome with test counts.
        """
        result = self.shell.run(test_cmd, cwd=worktree_path)
        combined = result.stdout + result.stderr
        success = result.exit_code == 0

        passed, failed = self._parse_pytest_counts(combined)
        total = passed + failed
        # Partial score: fraction of tests passing (0.0 if no tests detected)
        score = (passed / total) if total > 0 else (1.0 if success else 0.0)

        return EvalOutcome(
            success=success,
            eval_score=score,
            output=combined,
            tests_passed=passed,
            tests_failed=failed,
            tests_total=total,
        )
