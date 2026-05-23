import pytest
import os
import subprocess
from src.features.patch import PatchApplier
from src.features.shell import ShellExecutor

@pytest.fixture
def temp_repo_with_file(tmp_path):
    repo_dir = tmp_path / "patch_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True)
    (repo_dir / "app.py").write_text("def hello():\n    print('hi')\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo_dir, check=True)
    return repo_dir

def test_patch_applier_success(temp_repo_with_file):
    patch_content = (
        "diff --git a/app.py b/app.py\n"
        "index 123..456 100644\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def hello():\n"
        "-    print('hi')\n"
        "+    print('hello world')\n"
    )
    
    applier = PatchApplier()
    success = applier.apply(worktree_path=str(temp_repo_with_file), patch_text=patch_content)
    
    assert success is True
    content = (temp_repo_with_file / "app.py").read_text()
    assert "hello world" in content

def test_patch_applier_failure(temp_repo_with_file):
    # Invalid patch
    patch_content = "invalid patch"
    applier = PatchApplier()
    success = applier.apply(worktree_path=str(temp_repo_with_file), patch_text=patch_content)
    assert success is False
