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
    mock_shell.run.return_value = ShellResult(stdout="Tests failed", stderr="Error", exit_code=1)

    engine = EvalEngine(shell=mock_shell)
    result = engine.evaluate(worktree_path="/tmp/wt", test_cmd="pytest")

    assert result.success is False
    assert result.eval_score == 0.0


def test_eval_engine_parses_pytest_passed_count():
    mock_shell = MagicMock(spec=ShellExecutor)
    mock_shell.run.return_value = ShellResult(
        stdout="collected 10 items\n\n5 passed, 2 failed in 3.2s", stderr="", exit_code=1
    )
    engine = EvalEngine(shell=mock_shell)
    result = engine.evaluate("/tmp/wt", "pytest")

    assert result.tests_passed == 5
    assert result.tests_failed == 2
    assert result.tests_total == 7


def test_eval_engine_partial_score():
    """eval_score = passed/total when tests are detected."""
    mock_shell = MagicMock(spec=ShellExecutor)
    mock_shell.run.return_value = ShellResult(
        stdout="8 passed, 2 failed in 1s", stderr="", exit_code=1
    )
    engine = EvalEngine(shell=mock_shell)
    result = engine.evaluate("/tmp/wt", "pytest")

    assert result.eval_score == pytest.approx(0.8)


def test_eval_engine_all_passed_score_one():
    mock_shell = MagicMock(spec=ShellExecutor)
    mock_shell.run.return_value = ShellResult(
        stdout="12 passed in 2.1s", stderr="", exit_code=0
    )
    engine = EvalEngine(shell=mock_shell)
    result = engine.evaluate("/tmp/wt", "pytest")

    assert result.tests_passed == 12
    assert result.eval_score == pytest.approx(1.0)


def test_eval_engine_no_tests_detected_uses_exit_code():
    """When no pytest pattern found, fall back to exit-code-based score."""
    mock_shell = MagicMock(spec=ShellExecutor)
    mock_shell.run.return_value = ShellResult(
        stdout="some custom test output", stderr="", exit_code=0
    )
    engine = EvalEngine(shell=mock_shell)
    result = engine.evaluate("/tmp/wt", "make test")

    assert result.eval_score == 1.0
    assert result.tests_passed == 0  # no pattern detected
