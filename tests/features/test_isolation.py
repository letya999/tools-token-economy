import os
import shutil
import subprocess

import pytest

from src.features.isolation import GitIsolationProvider


@pytest.fixture
def temp_repo(tmp_path):
    git_cmd = shutil.which("git") or "git"
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run([git_cmd, "init"], cwd=repo_dir, check=True, capture_output=True)
    (repo_dir / "file.txt").write_text("initial content")
    subprocess.run([git_cmd, "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run([git_cmd, "config", "user.email", "test@example.com"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run([git_cmd, "config", "user.name", "Test User"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run([git_cmd, "commit", "-m", "initial commit"], cwd=repo_dir, check=True, capture_output=True)
    return repo_dir


def test_git_isolation_provider_setup_teardown(temp_repo, tmp_path):
    git_cmd = shutil.which("git") or "git"
    worktree_base = tmp_path / "worktrees"
    provider = GitIsolationProvider(str(temp_repo), str(worktree_base))
    
    run_id = "test_run_1"
    wt_path = provider.setup(run_id)
    
    assert os.path.exists(wt_path)
    assert os.path.isfile(os.path.join(wt_path, "file.txt"))
    
    provider.teardown(run_id)
    
    # Verify worktree is removed from git list
    result = subprocess.run(
        [git_cmd, "worktree", "list"],
        cwd=str(temp_repo),
        capture_output=True,
        text=True,
        check=False
    )
    assert str(wt_path) not in result.stdout
