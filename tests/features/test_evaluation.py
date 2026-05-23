import pytest

from src.features.evaluation import EvalEngine


def test_eval_engine_parses_passed(tmp_path):
    mock_shell = pytest.importorskip("unittest.mock").MagicMock()
    mock_shell.run.return_value.stdout = "7 passed, 0 failed"
    mock_shell.run.return_value.stderr = ""
    mock_shell.run.return_value.exit_code = 0

    engine = EvalEngine(shell=mock_shell)
    result = engine.evaluate(worktree_path=str(tmp_path), test_cmd="pytest")

    assert result.success is True
    assert result.tests_passed == 7
    assert result.tests_total == 7


def test_eval_engine_parses_failed(tmp_path):
    mock_shell = pytest.importorskip("unittest.mock").MagicMock()
    mock_shell.run.return_value.stdout = "5 passed, 2 failed"
    mock_shell.run.return_value.stderr = ""
    mock_shell.run.return_value.exit_code = 1

    engine = EvalEngine(shell=mock_shell)
    result = engine.evaluate(worktree_path=str(tmp_path), test_cmd="pytest")

    assert result.success is False
    assert result.tests_failed == 2
    assert result.tests_passed == 5


def test_eval_engine_score_calculation(tmp_path):
    mock_shell = pytest.importorskip("unittest.mock").MagicMock()
    mock_shell.run.return_value.stdout = "4 passed, 1 failed"
    mock_shell.run.return_value.stderr = ""
    mock_shell.run.return_value.exit_code = 1

    engine = EvalEngine(shell=mock_shell)
    result = engine.evaluate(str(tmp_path), "pytest")

    # 4/5 = 0.8
    assert result.eval_score == pytest.approx(0.8)


def test_eval_engine_handles_errors(tmp_path):
    mock_shell = pytest.importorskip("unittest.mock").MagicMock()
    mock_shell.run.return_value.stdout = "0 passed, 0 failed, 1 error"
    mock_shell.run.return_value.stderr = "Traceback..."
    mock_shell.run.return_value.exit_code = 1

    engine = EvalEngine(shell=mock_shell)
    result = engine.evaluate(str(tmp_path), "pytest")

    assert result.success is False
    assert result.eval_score == 0.0


def test_eval_engine_fallback_score(tmp_path):
    mock_shell = pytest.importorskip("unittest.mock").MagicMock()
    mock_shell.run.return_value.stdout = "Successfully ran non-pytest command"
    mock_shell.run.return_value.stderr = ""
    mock_shell.run.return_value.exit_code = 0

    engine = EvalEngine(shell=mock_shell)
    result = engine.evaluate(str(tmp_path), "make test")

    # No tests detected, but exit code 0 -> score 1.0
    assert result.eval_score == 1.0
