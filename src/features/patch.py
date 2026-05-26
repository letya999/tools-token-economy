"""
Multi-strategy patch applicator.

Strategy order:
1. git apply --ignore-whitespace --whitespace=nowarn  (fast, tolerant of whitespace)
2. git apply --ignore-whitespace --recount            (recount lines, tolerate off-by-one)  
3. patch -p1 --ignore-whitespace --fuzz=3             (fuzzy, GNU patch)
4. Pure-additive fast-path: if patch has ONLY '+' lines (no '-' context deletions),
   extract additions and append to file directly.

On all failures, return a DETAILED error with the actual git apply output so the
agent knows exactly what went wrong.
"""
import os
import re
import shutil
import subprocess

from src.features.shell import ShellExecutor


class PatchApplier:
    def __init__(self, shell: ShellExecutor | None = None):
        self.shell = shell or ShellExecutor()

    def apply(self, worktree_path: str, patch_text: str) -> tuple[bool, str]:
        """
        Apply patch_text to worktree_path. Returns (success, error_detail).
        error_detail is empty string on success, helpful message on failure.
        """
        if not patch_text.strip():
            return True, ""

        patch_file = os.path.join(worktree_path, ".benchmark_patch")
        try:
            with open(patch_file, "w", encoding="utf-8") as f:
                f.write(patch_text)

            # Strategy 1: git apply --ignore-whitespace
            ok, err = self._try_git_apply(worktree_path, patch_file, ["--ignore-whitespace", "--whitespace=nowarn"])
            if ok:
                return True, ""

            # Strategy 2: git apply --ignore-whitespace --recount
            ok, err2 = self._try_git_apply(worktree_path, patch_file, ["--ignore-whitespace", "--recount"])
            if ok:
                return True, ""

            # Strategy 3: GNU patch -p1 --fuzz=3
            if shutil.which("patch"):
                ok, err3 = self._try_gnu_patch(worktree_path, patch_file)
                if ok:
                    return True, ""
            else:
                err3 = "GNU patch not available"

            # Strategy 4: pure-additive fast-path (append)
            ok, err4 = self._try_additive_append(worktree_path, patch_text)
            if ok:
                return True, ""

            # All failed — return combined error detail
            detail = (
                f"All patch strategies failed.\n"
                f"git apply: {err}\n"
                f"git apply --recount: {err2}\n"
                f"GNU patch: {err3}\n"
                f"Additive append: {err4}\n\n"
                f"HINT: Your patch has incorrect line numbers or context. "
                f"Use the 'read' tool to get exact file content, then generate a "
                f"correct unified diff with matching context lines. "
                f"Or use 'write' to write the complete file from scratch."
            )
            return False, detail

        finally:
            if os.path.exists(patch_file):
                os.remove(patch_file)

    def _try_git_apply(self, cwd: str, patch_file: str, extra_flags: list[str]) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["git", "apply"] + extra_flags + [patch_file],
                cwd=cwd, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return True, ""
            return False, (result.stderr or result.stdout).strip()[:300]
        except Exception as e:
            return False, str(e)

    def _try_gnu_patch(self, cwd: str, patch_file: str) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["patch", "-p1", "--ignore-whitespace", "--fuzz=3", "-i", patch_file],
                cwd=cwd, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return True, ""
            return False, (result.stderr or result.stdout).strip()[:300]
        except Exception as e:
            return False, str(e)

    def _try_additive_append(self, cwd: str, patch_text: str) -> tuple[bool, str]:
        """
        Fast-path for pure-additive patches: if patch only adds lines to one file,
        extract the additions and append them.
        """
        lines = patch_text.splitlines()
        
        # Find target file
        target_file = None
        additions = []
        has_deletions = False
        
        for line in lines:
            if line.startswith("+++ b/"):
                target_file = line[6:].strip()
            elif line.startswith("--- ") or line.startswith("+++ "):
                continue
            elif line.startswith("-") and not line.startswith("---"):
                has_deletions = True
                break
            elif line.startswith("+"):
                additions.append(line[1:])
        
        if has_deletions or not target_file or not additions:
            return False, "Patch has deletions or no target file — cannot use additive fast-path"
        
        real_cwd = os.path.realpath(cwd)
        full_path = os.path.realpath(os.path.join(cwd, target_file))
        if not (full_path.startswith(real_cwd + os.sep) or full_path == real_cwd):
            return False, f"Path traversal blocked: {target_file}"
        if not os.path.isfile(full_path):
            return False, f"Target file not found: {target_file}"
        
        try:
            with open(full_path, "a", encoding="utf-8") as f:
                f.write("\n" + "\n".join(additions) + "\n")
            return True, ""
        except Exception as e:
            return False, str(e)
