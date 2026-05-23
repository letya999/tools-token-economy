import os
import shutil
import subprocess


class GitIsolationProvider:
    """
    Provides environment isolation using git worktree.
    """
    def __init__(self, repo_path: str, worktree_base: str):
        self.repo_path = os.path.abspath(repo_path)
        self.worktree_base = os.path.abspath(worktree_base)
        self.active_worktrees: dict[str, str] = {}
        self.git_cmd = shutil.which("git") or "git"

    def setup(self, run_id: str) -> str:
        """
        Creates a new worktree for a specific run.
        """
        wt_path = os.path.join(self.worktree_base, run_id)

        if os.path.exists(wt_path):
            shutil.rmtree(wt_path)

        subprocess.run(
            [self.git_cmd, "worktree", "add", wt_path, "HEAD"],
            cwd=self.repo_path,
            check=True,
            capture_output=True
        )

        self.active_worktrees[run_id] = wt_path
        return wt_path

    def teardown(self, run_id: str):
        """
        Removes the worktree after the run completes.
        """
        wt_path = self.active_worktrees.get(run_id)
        if not wt_path:
            return

        subprocess.run(
            [self.git_cmd, "worktree", "remove", "--force", wt_path],
            cwd=self.repo_path,
            check=True,
            capture_output=True
        )

        if os.path.exists(wt_path):
            shutil.rmtree(wt_path, ignore_errors=True)

        if run_id in self.active_worktrees:
            del self.active_worktrees[run_id]
