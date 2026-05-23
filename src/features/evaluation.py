from typing import Optional
from dataclasses import dataclass
from src.features.shell import ShellExecutor

@dataclass
class EvalOutcome:
    success: bool
    eval_score: float
    output: str

class EvalEngine:
    """
    Runs tests and evaluates the result of task execution.
    """
    def __init__(self, shell: Optional[ShellExecutor] = None):
        self.shell = shell or ShellExecutor()

    def evaluate(self, worktree_path: str, test_cmd: str) -> EvalOutcome:
        """
        Runs the test command in the specified path.
        """
        result = self.shell.run(test_cmd, cwd=worktree_path)
        
        # Base logic: exit_code 0 -> success (1.0), else failure (0.0)
        success = result.exit_code == 0
        score = 1.0 if success else 0.0
        
        return EvalOutcome(
            success=success,
            eval_score=score,
            output=result.stdout + result.stderr
        )
