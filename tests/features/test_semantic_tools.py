
import pytest

from src.features.tool_registry.semantic_tools import SimpleRagTool


@pytest.fixture
def temp_repo(tmp_path):
    workspace = tmp_path / "semantic_repo"
    workspace.mkdir()
    (workspace / "a.py").write_text("def find_user(id):\n    pass")
    (workspace / "b.py").write_text("def delete_order(id):\n    pass")
    return str(workspace)

def test_simple_rag_tool(temp_repo):
    tool = SimpleRagTool(worktree_path=temp_repo)
    # Search for something that matches a.py
    res = tool.execute(query="find user")

    assert "a.py" in res.output
    assert "find_user" in res.output
    assert res.tokens > 0

def test_simple_rag_tool_no_match(temp_repo):
    tool = SimpleRagTool(worktree_path=temp_repo)
    res = tool.execute(query="rocket science")
    # Should not crash, maybe return empty or low rank
    assert res.tokens >= 0
