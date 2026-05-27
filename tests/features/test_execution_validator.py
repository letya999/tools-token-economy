import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.features.execution_validator import ExecutionResult, ExecutionValidator


@pytest.fixture
def validator(tmp_path):
    return ExecutionValidator(str(tmp_path))


def _mock_status(files: str):
    return MagicMock(stdout=files, returncode=0)


def _mock_popen(stdout: str, stderr: str, returncode: int):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = (stdout, stderr)
    mock_proc.returncode = returncode
    return mock_proc


def test_no_changed_files_returns_not_verified(validator):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = _mock_status("")
        res = validator.validate(validation_cmd=None, test_cmd=None, baseline_pass_count=None)
    assert res.outcome == "not_verified"
    assert res.method_used == "none"


def test_validation_cmd_success(validator):
    with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen:
        mock_run.return_value = _mock_status(" M src/foo.py\n")
        mock_popen.return_value = _mock_popen("ok", "", 0)
        res = validator.validate(validation_cmd="make check", test_cmd=None, baseline_pass_count=None)
    assert res.outcome == "passed"
    assert res.method_used == "validation_cmd"


def test_validation_cmd_failure(validator):
    with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen:
        mock_run.return_value = _mock_status(" M src/foo.py\n")
        mock_popen.return_value = _mock_popen("", "error!", 1)
        res = validator.validate(validation_cmd="make check", test_cmd=None, baseline_pass_count=None)
    assert res.outcome == "failed"


def test_env_error_detected_by_exit_code(validator):
    with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen:
        mock_run.return_value = _mock_status(" M src/foo.py\n")
        mock_popen.return_value = _mock_popen("", "some error", 127)
        res = validator.validate(validation_cmd="missing_cmd", test_cmd=None, baseline_pass_count=None)
    assert res.outcome == "env_error"


def test_env_error_detected_by_stderr_pattern(validator):
    with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen:
        mock_run.return_value = _mock_status(" M src/foo.py\n")
        mock_popen.return_value = _mock_popen("", "ModuleNotFoundError: No module named 'foo'", 1)
        res = validator.validate(validation_cmd="python run.py", test_cmd=None, baseline_pass_count=None)
    assert res.outcome == "env_error"


def test_env_error_detected_by_stdout_pattern(validator):
    with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen:
        mock_run.return_value = _mock_status(" M src/foo.py\n")
        # Pytest collection error in stdout
        mock_popen.return_value = _mock_popen("E ModuleNotFoundError: No module named 'missing'", "", 1)
        res = validator.validate(validation_cmd="pytest", test_cmd=None, baseline_pass_count=None)
    assert res.outcome == "env_error"


def test_test_cmd_with_no_baseline(validator):
    with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen:
        mock_run.return_value = _mock_status("?? tests/test_new.py\n")
        mock_popen.return_value = _mock_popen("3 passed in 0.5s", "", 0)
        res = validator.validate(validation_cmd=None, test_cmd="pytest", baseline_pass_count=None)
    assert res.outcome == "passed"
    assert res.tests_passed == 3


def test_test_cmd_with_baseline_regression(validator):
    with patch("subprocess.run") as mock_run, patch("subprocess.Popen") as mock_popen:
        mock_run.return_value = _mock_status("M tests/test_existing.py\n")
        mock_popen.return_value = _mock_popen("4 passed in 0.5s", "", 0)
        # Baseline was 5 — we now have fewer passing tests
        res = validator.validate(validation_cmd=None, test_cmd="pytest", baseline_pass_count=5)
    assert res.outcome == "failed"


def test_syntax_check_passes(validator, tmp_path):
    py_file = tmp_path / "valid.py"
    py_file.write_text("x = 1\n")
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            _mock_status(f" M {py_file.name}\n"),
            MagicMock(returncode=0),  # py_compile
        ]
        res = validator.validate(validation_cmd=None, test_cmd=None, baseline_pass_count=None)
    assert res.outcome == "not_verified"
    assert res.method_used == "syntax_check"


def test_syntax_check_fails(validator, tmp_path):
    py_file = tmp_path / "bad.py"
    py_file.write_text("def broken(\n")
    with patch("subprocess.run") as mock_run:
        # git status returns the .py file
        mock_run.return_value = _mock_status(f" M {py_file.name}\n")
        # py_compile raises CalledProcessError
        import subprocess as sp
        error = sp.CalledProcessError(1, "py_compile", stderr="SyntaxError: unexpected EOF")

        def side_effect(*args, **kwargs):
            if "py_compile" in str(args):
                raise error
            return _mock_status(f" M {py_file.name}\n")

        mock_run.side_effect = side_effect
        res = validator.validate(validation_cmd=None, test_cmd=None, baseline_pass_count=None)
    assert res.outcome == "failed"
    assert res.method_used == "syntax_check"
