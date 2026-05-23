import shutil
import subprocess

import pytest

from src.features.tool_registry.grep_tools import GitGrepTool, GrepTool, RgTool


@pytest.fixture
def temp_repo(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    git_cmd = shutil.which("git") or "git"
    
    # Init git repo to test git_grep
    subprocess.run([git_cmd, "init"], cwd=workspace, check=True, capture_output=True)

    # Create test files
    (workspace / "test.txt").write_text("hello world\npython search\n")
    (workspace / "code.py").write_text("def hello():\n    print('hello world')\n")

    subprocess.run([git_cmd, "add", "."], cwd=workspace, check=True, capture_output=True)
    subprocess.run([git_cmd, "config", "user.email", "test@example.com"], cwd=workspace, check=True, capture_output=True)
    subprocess.run([git_cmd, "config", "user.name", "Test User"], cwd=workspace, check=True, capture_output=True)
    subprocess.run([git_cmd, "commit", "-m", "init"], cwd=workspace, check=True, capture_output=True)

    return str(workspace)


def test_grep_tool(temp_repo):
    if not shutil.which("grep"):
        pytest.skip("grep not installed")
    tool = GrepTool(temp_repo)
    res = tool.execute(pattern="python")
    assert "test.txt" in res.output
    assert "python search" in res.output


def test_git_grep_tool(temp_repo):
    tool = GitGrepTool(temp_repo)
    res = tool.execute(pattern="hello")
    assert "code.py" in res.output
    assert "test.txt" in res.output


def test_rg_tool(temp_repo):
    # Skip if rg is not installed locally
    if not shutil.which("rg"):
        pytest.skip("ripgrep not installed")
    
    tool = RgTool(temp_repo)
    res = tool.execute(pattern="world")
    assert "hello world" in res.output
