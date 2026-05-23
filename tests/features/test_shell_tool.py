import pytest
from unittest.mock import patch, MagicMock
from src.features.tool_registry.shell_tool import ShellTool
from src.features.shell import ShellResult


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "README.md").write_text("# Test")
    return str(tmp_path)


def test_shell_tool_runs_command(repo):
    tool = ShellTool(repo)
    with patch.object(tool.executor, "run") as mock_run:
        mock_run.return_value = ShellResult(stdout="hello world", stderr="", exit_code=0)
        res = tool.execute(command="echo hello world")
    assert "hello world" in res.output
    assert res.token_count > 0
    mock_run.assert_called_once_with("echo hello world", cwd=repo, timeout=30.0)


def test_shell_tool_includes_stderr(repo):
    tool = ShellTool(repo)
    with patch.object(tool.executor, "run") as mock_run:
        mock_run.return_value = ShellResult(stdout="out", stderr="some warning", exit_code=0)
        res = tool.execute(command="cmd")
    assert "STDERR" in res.output
    assert "some warning" in res.output


def test_shell_tool_empty_output_shows_exit_code(repo):
    tool = ShellTool(repo)
    with patch.object(tool.executor, "run") as mock_run:
        mock_run.return_value = ShellResult(stdout="", stderr="", exit_code=0)
        res = tool.execute(command="true")
    assert "exit code" in res.output


def test_shell_tool_custom_timeout(repo):
    tool = ShellTool(repo)
    with patch.object(tool.executor, "run") as mock_run:
        mock_run.return_value = ShellResult(stdout="done", stderr="", exit_code=0)
        tool.execute(command="sleep 1", timeout=60.0)
    _, kwargs = mock_run.call_args
    assert kwargs.get("timeout") == 60.0


def test_shell_tool_name_and_description(repo):
    tool = ShellTool(repo)
    assert tool.name == "shell"
    assert "bash" in tool.description.lower() or "command" in tool.description.lower()
