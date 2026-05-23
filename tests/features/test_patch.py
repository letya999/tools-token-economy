import shutil
import subprocess

import pytest

from src.features.patch import PatchApplier


@pytest.fixture
def temp_repo_with_file(tmp_path):
    git_cmd = shutil.which("git") or "git"
    repo_dir = tmp_path / "patch_repo"
    repo_dir.mkdir()
    subprocess.run([git_cmd, "init"], cwd=repo_dir, check=True, capture_output=True)
    (repo_dir / "app.py").write_text("def hello():\n    print('hi')\n")
    subprocess.run([git_cmd, "add", "."], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run([git_cmd, "config", "user.email", "test@example.com"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run([git_cmd, "config", "user.name", "Test User"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run([git_cmd, "commit", "-m", "initial commit"], cwd=repo_dir, check=True, capture_output=True)
    return repo_dir


def test_patch_applier_success(temp_repo_with_file):
    patch_content = (
        "--- app.py\n"
        "+++ app.py\n"
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


def test_patch_applier_invalid_patch(temp_repo_with_file):
    applier = PatchApplier()
    # Invalid diff format
    success = applier.apply(str(temp_repo_with_file), "not a patch")
    assert success is False
