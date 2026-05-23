import os
import subprocess
from typing import Optional
from src.features.shell import ShellExecutor

class PatchApplier:
    """
    Applies patches to the repository.
    """
    def __init__(self, shell: Optional[ShellExecutor] = None):
        self.shell = shell or ShellExecutor()

    def apply(self, worktree_path: str, patch_text: str) -> bool:
        """
        Applies patch text using 'git apply'.
        """
        if not patch_text.strip():
            return True
            
        patch_file = os.path.join(worktree_path, "current_run.patch")
        try:
            with open(patch_file, "w") as f:
                f.write(patch_text)
            
            result = self.shell.run("git apply current_run.patch", cwd=worktree_path)
            
            return result.exit_code == 0
        finally:
            if os.path.exists(patch_file):
                os.remove(patch_file)
