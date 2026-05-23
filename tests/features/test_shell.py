import pytest
import sys
from src.features.shell import ShellExecutor

def test_shell_executor_success():
    executor = ShellExecutor()
    # Use cross-platform echo logic
    cmd = 'python -c "print(\'hello world\')"'
    result = executor.run(cmd)
    assert result.stdout.strip() == "hello world"
    assert result.exit_code == 0

def test_shell_executor_failure():
    executor = ShellExecutor()
    result = executor.run("non_existent_command_12345")
    assert result.exit_code != 0

def test_shell_executor_timeout():
    executor = ShellExecutor()
    # Use python for cross-platform sleep
    cmd = 'python -c "import time; time.sleep(2)"'
    with pytest.raises(TimeoutError):
        executor.run(cmd, timeout=0.1)
