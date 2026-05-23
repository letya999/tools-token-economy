import shlex

from src.core.tools import BaseTool, ToolResult
from src.features.shell import ShellExecutor


class GrepTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("grep", "Standard recursive grep search")
        self.worktree_path = worktree_path
        self.shell = ShellExecutor()

    def execute(self, pattern: str) -> ToolResult:
        safe_pattern = shlex.quote(pattern)
        cmd = f"grep -rnI {safe_pattern} ."
        result = self.shell.run(cmd, cwd=self.worktree_path)

        output = result.stdout.strip()
        if not output and result.stderr:
            output = result.stderr.strip()
        elif not output:
            output = "No matches found."

        return self.format_result(output)

class GitGrepTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("git_grep", "Git grep search (only tracked files)")
        self.worktree_path = worktree_path
        self.shell = ShellExecutor()

    def execute(self, pattern: str) -> ToolResult:
        safe_pattern = shlex.quote(pattern)
        cmd = f"git grep -n {safe_pattern}"
        result = self.shell.run(cmd, cwd=self.worktree_path)

        output = result.stdout.strip()
        if not output and result.stderr:
            output = result.stderr.strip()
        elif not output:
            output = "No matches found."

        return self.format_result(output)

class RgTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("rg", "Ripgrep search (if installed)")
        self.worktree_path = worktree_path
        self.shell = ShellExecutor()

    def execute(self, pattern: str) -> ToolResult:
        safe_pattern = shlex.quote(pattern)
        cmd = f"rg -n {safe_pattern}"
        result = self.shell.run(cmd, cwd=self.worktree_path)

        output = result.stdout.strip()
        if not output and result.stderr:
            output = result.stderr.strip()
        elif not output:
            output = "No matches found."

        return self.format_result(output)

class UgrepTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("ugrep", "Ugrep search")
        self.worktree_path = worktree_path
        self.shell = ShellExecutor()

    def execute(self, pattern: str) -> ToolResult:
        safe_pattern = shlex.quote(pattern)
        cmd = f"ugrep -n {safe_pattern}"
        result = self.shell.run(cmd, cwd=self.worktree_path)

        output = result.stdout.strip()
        if not output and result.stderr:
            output = result.stderr.strip()
        elif not output:
            output = "No matches found."

        return self.format_result(output)

class SemgrepTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("semgrep", "Semgrep structural search")
        self.worktree_path = worktree_path
        self.shell = ShellExecutor()

    def execute(self, pattern: str) -> ToolResult:
        safe_pattern = shlex.quote(pattern)
        cmd = f"semgrep --pattern {safe_pattern} --quiet"
        result = self.shell.run(cmd, cwd=self.worktree_path)

        output = result.stdout.strip()
        if not output and result.stderr:
            output = result.stderr.strip()
        elif not output:
            output = "No matches found."

        return self.format_result(output)
