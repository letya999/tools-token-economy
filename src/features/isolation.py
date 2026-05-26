import logging
import os
import shutil
import subprocess

_log = logging.getLogger(__name__)


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

        # Cleanup if directory already exists
        if os.path.exists(wt_path):
            try:
                shutil.rmtree(wt_path)
            except Exception:
                _log.debug("Manual rmtree failed, trying worktree prune for %s", wt_path)
                subprocess.run([self.git_cmd, "worktree", "prune"], cwd=self.repo_path)
                shutil.rmtree(wt_path, ignore_errors=True)

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
        if not wt_path and self.worktree_base:
            wt_path = os.path.join(self.worktree_base, run_id)
        
        if not wt_path:
            return

        # 1. Try official remove
        try:
            subprocess.run(
                [self.git_cmd, "worktree", "remove", "--force", wt_path],
                cwd=self.repo_path, capture_output=True, timeout=15
            )
        except Exception as e:
            _log.warning("git worktree remove failed for %s: %s", wt_path, e)

        # 2. Prune metadata
        try:
            subprocess.run([self.git_cmd, "worktree", "prune"], cwd=self.repo_path, capture_output=True)
        except Exception as e:
            _log.debug("git worktree prune failed: %s", e)

        # 3. Aggressive filesystem cleanup
        if os.path.exists(wt_path):
            try:
                shutil.rmtree(wt_path, ignore_errors=True)
            except Exception as e:
                _log.debug("Final rmtree failed for %s: %s", wt_path, e)

        if run_id in self.active_worktrees:
            del self.active_worktrees[run_id]
