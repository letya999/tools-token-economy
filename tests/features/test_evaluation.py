import pytest
from src.features.evaluation import EvalEngine
from src.features.shell import ShellExecutor, ShellResult
from unittest.mock import MagicMock

def test_eval_engine_success():
    mock_shell = MagicMock(spec=ShellExecutor)
    # Simulate test_cmd passing
    mock_shell.run.return_value = ShellResult(stdout="Tests passed", stderr="", exit_code=0)
    
    engine = EvalEngine(shell=mock_shell)
    result = engine.evaluate(worktree_path="/tmp/wt", test_cmd="pytest")
    
    assert result.success is True
    assert result.eval_score == 1.0

def test_eval_engine_failure():
    mock_shell = MagicMock(spec=ShellExecutor)
    # Simulate test_cmd failing
    mock_shell.run.return_value = ShellResult(stdout="Tests failed", stderr="Error", exit_code=1)
    
    engine = EvalEngine(shell=mock_shell)
    result = engine.evaluate(worktree_path="/tmp/wt", test_cmd="pytest")
    
    assert result.success is False
    assert result.eval_score == 0.0
