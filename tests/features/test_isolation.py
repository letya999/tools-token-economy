import pytest
import os
import shutil
import subprocess
from src.features.isolation import GitIsolationProvider

@pytest.fixture
def temp_repo(tmp_path):
    # Создаем временный git-репозиторий для тестов
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True)
    (repo_dir / "file.txt").write_text("initial content")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo_dir, check=True)
    return repo_dir

def test_git_isolation_provider_lifecycle(temp_repo, tmp_path):
    worktree_parent = tmp_path / "worktrees"
    worktree_parent.mkdir()
    
    provider = GitIsolationProvider(repo_path=str(temp_repo), worktree_base=str(worktree_parent))
    
    # Setup
    wt_path = provider.setup(run_id="test_run")
    assert os.path.exists(wt_path)
    assert os.path.exists(os.path.join(wt_path, "file.txt"))
    
    # Verify it's a separate path
    assert str(wt_path).startswith(str(worktree_parent))
    
    # Teardown
    provider.teardown(run_id="test_run")
    assert not os.path.exists(wt_path)
    
    # Verify worktree is removed from git list
    result = subprocess.run(["git", "worktree", "list"], cwd=temp_repo, capture_output=True, text=True)
    assert str(wt_path) not in result.stdout
