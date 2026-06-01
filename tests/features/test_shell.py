from unittest.mock import patch

import pytest

from src.features.shell import ShellExecutor


def test_shell_executor_success():
    executor = ShellExecutor()
    # Use 'echo' which is standard in both Windows and Linux (WSL)
    # On Windows, we need to handle how 'shell=True' works if we were strictly native,
    # but here we just want to verify the executor returns SOMETHING.
    result = executor.run("echo hello_world")
    assert "hello_world" in result.stdout
    assert result.exit_code == 0

def test_shell_executor_failure():
    executor = ShellExecutor()
    result = executor.run("non_existent_command_12345")
    assert result.exit_code != 0

def test_shell_executor_timeout_mocked():
    """Mock the subprocess.run to raise TimeoutExpired to verify our handler."""
    import subprocess
    executor = ShellExecutor()
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="sleep 2", timeout=0.1)):
        with pytest.raises(TimeoutError):
            executor.run("sleep 2", timeout=0.1)
