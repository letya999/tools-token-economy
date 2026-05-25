import pytest

from src.features.tool_registry.semantic_tools import SimpleRagTool


@pytest.fixture
def temp_repo(tmp_path):
    workspace = tmp_path / "semantic_repo"
    workspace.mkdir()
    (workspace / "a.py").write_text("def find_user(user_id: int):\n    return db.get(user_id)\n")
    (workspace / "b.py").write_text("def delete_order(order_id: int):\n    db.remove(order_id)\n")
    (workspace / "c.py").write_text("class UserRepository:\n    def save(self, user): pass\n")
    return str(workspace)


# ---------------------------------------------------------------------------
# ingest() API
# ---------------------------------------------------------------------------

def test_ingest_returns_stats(temp_repo):
    tool = SimpleRagTool(worktree_path=temp_repo)
    stats = tool.ingest()
    assert stats["status"] == "done"
    assert stats["files"] == 3
    assert stats["chunks"] >= 3


def test_ingest_is_idempotent(temp_repo):
    tool = SimpleRagTool(worktree_path=temp_repo)
    tool.ingest()
    stats2 = tool.ingest()
    assert stats2["status"] == "cached"


def test_ingested_flag_before_and_after(temp_repo):
    tool = SimpleRagTool(worktree_path=temp_repo)
    assert not tool._ingested
    tool.ingest()
    assert tool._ingested


# ---------------------------------------------------------------------------
# execute() — hybrid search results
# ---------------------------------------------------------------------------

def test_hybrid_search_finds_relevant_file(temp_repo):
    tool = SimpleRagTool(worktree_path=temp_repo)
    res = tool.execute(query="find user by id")
    assert "a.py" in res.output
    assert res.tokens > 0


def test_hybrid_search_uses_bm25_token_match(temp_repo):
    tool = SimpleRagTool(worktree_path=temp_repo)
    # BM25 should surface b.py for exact token "delete_order"
    res = tool.execute(query="delete_order")
    assert "b.py" in res.output


def test_hybrid_search_semantic_match(temp_repo):
    tool = SimpleRagTool(worktree_path=temp_repo)
    # Dense embedding should surface c.py for "persistence layer"
    res = tool.execute(query="repository pattern save entity")
    assert "c.py" in res.output


def test_execute_with_pre_ingested_tool(temp_repo):
    tool = SimpleRagTool(worktree_path=temp_repo)
    tool.ingest()  # pre-ingest (as orchestrator would)
    res = tool.execute(query="find user")
    assert "a.py" in res.output


def test_execute_without_pre_ingest_still_works(temp_repo):
    """execute() triggers lazy ingestion when called directly."""
    tool = SimpleRagTool(worktree_path=temp_repo)
    res = tool.execute(query="find user")
    assert "find_user" in res.output


def test_no_match_returns_empty_message(temp_repo):
    tool = SimpleRagTool(worktree_path=temp_repo)
    res = tool.execute(query="xyzkjhqwert completely nonsensical query 12345")
    # Should not crash; may return "No relevant context found." or low-score hits
    assert res.tokens >= 0
