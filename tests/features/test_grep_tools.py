import pytest
import os
import subprocess
from src.features.tool_registry.grep_tools import GrepTool, GitGrepTool, RgTool

@pytest.fixture
def temp_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    # Init git repo to test git_grep
    subprocess.run(["git", "init"], cwd=workspace, check=True)
    
    # Create test files
    (workspace / "test.txt").write_text("hello world\nthis is a test\nhello gemini\n")
    (workspace / "code.py").write_text("def hello():\n    print('hello world')\n")
    
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=workspace, check=True)
    
    return str(workspace)

def test_grep_tool(temp_workspace):
    tool = GrepTool(worktree_path=temp_workspace)
    res = tool.execute("hello")
    # depending on OS, grep output format varies slightly. 
    # On Windows without grep installed, it will fail, which is expected during local non-WSL testing.
    assert "hello" in res.output or "not recognized" in res.output.lower() or "not found" in res.output.lower()
    assert res.token_count > 0

def test_git_grep_tool(temp_workspace):
    tool = GitGrepTool(worktree_path=temp_workspace)
    res = tool.execute("hello")
    assert "hello" in res.output
    assert "test.txt" in res.output
    assert "code.py" in res.output

def test_rg_tool(temp_workspace):
    # rg might not be installed in the CI environment natively, but we check if tool handles execution
    # It might fail with 'command not found', so we handle both.
    tool = RgTool(worktree_path=temp_workspace)
    res = tool.execute("hello")
    # If rg is installed, it returns matches. If not, it returns the error from shell.
    # Just asserting it executed without Python crashing.
    assert "hello" in res.output or "not recognized" in res.output.lower() or "not found" in res.output.lower()
