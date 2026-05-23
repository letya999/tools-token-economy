import pytest
import os
from src.features.tool_registry.basic_tools import FileReadTool, FileWriteTool, GlobTool

@pytest.fixture
def temp_workspace(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "test.txt").write_text("line 1\nline 2\nline 3\n")
    (workspace / "nested").mkdir()
    (workspace / "nested" / "inner.py").write_text("print('hello')")
    return str(workspace)

def test_file_read_tool(temp_workspace):
    tool = FileReadTool(worktree_path=temp_workspace)
    
    # Read full file
    res = tool.execute("test.txt")
    assert "line 1\nline 2\nline 3\n" in res.output
    assert res.token_count > 0
    
    # Read specific lines
    res_partial = tool.execute("test.txt", start_line=2, end_line=2)
    assert res_partial.output == "line 2\n"

def test_file_write_tool(temp_workspace):
    tool = FileWriteTool(worktree_path=temp_workspace)
    
    # Write to new file
    res = tool.execute("new_file.txt", "content here")
    assert "Successfully" in res.output
    
    with open(os.path.join(temp_workspace, "new_file.txt"), "r") as f:
        assert f.read() == "content here"

def test_glob_tool(temp_workspace):
    tool = GlobTool(worktree_path=temp_workspace)
    
    res = tool.execute("**/*.py")
    # depending on OS paths, normalize checks
    assert "inner.py" in res.output
    assert res.token_count > 0
