
import pytest

from src.features.tool_registry.structural_tools import RepoMapTool, TreeSitterTool


@pytest.fixture
def temp_python_repo(tmp_path):
    workspace = tmp_path / "py_repo"
    workspace.mkdir()
    (workspace / "main.py").write_text("def main():\n    print('hello')\n\nclass Worker:\n    def run(self):\n        pass\n")
    (workspace / "utils.py").write_text("def helper():\n    return 42\n")
    return str(workspace)

def test_tree_sitter_tool(temp_python_repo):
    tool = TreeSitterTool(worktree_path=temp_python_repo)
    res = tool.execute(file_path="main.py")

    assert "func.name: main" in res.output
    assert "class.name: Worker" in res.output
    assert res.tokens > 0

def test_repo_map_tool(temp_python_repo):
    tool = RepoMapTool(worktree_path=temp_python_repo)
    res = tool.execute()

    assert "main.py" in res.output
    assert "utils.py" in res.output
    assert "main" in res.output
    assert "Worker" in res.output
    assert "helper" in res.output
