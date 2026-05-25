import json

from src.core.tools import BaseTool, ToolResult
from src.features.shell import ShellExecutor


def _no_output(result_stdout: str, result_stderr: str) -> str:
    if result_stderr:
        return result_stderr.strip()
    return "No matches found."


class GrepTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("grep", "Standard recursive grep search")
        self.worktree_path = worktree_path
        self.shell = ShellExecutor()

    def execute(self, pattern: str) -> ToolResult:
        result = self.shell.run_args(["grep", "-rnI", pattern, "."], cwd=self.worktree_path)
        output = result.stdout.strip() or _no_output(result.stdout, result.stderr)
        return self.format_result(output)


class GitGrepTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("git_grep", "Git grep search (only tracked files)")
        self.worktree_path = worktree_path
        self.shell = ShellExecutor()

    def execute(self, pattern: str) -> ToolResult:
        result = self.shell.run_args(["git", "grep", "-n", pattern], cwd=self.worktree_path)
        output = result.stdout.strip() or _no_output(result.stdout, result.stderr)
        return self.format_result(output)


class RgTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("rg", "Ripgrep search (if installed)")
        self.worktree_path = worktree_path
        self.shell = ShellExecutor()

    def execute(self, pattern: str) -> ToolResult:
        result = self.shell.run_args(["rg", "-n", pattern, "."], cwd=self.worktree_path)
        output = result.stdout.strip() or _no_output(result.stdout, result.stderr)
        return self.format_result(output)


class UgrepTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("ugrep", "Ugrep search")
        self.worktree_path = worktree_path
        self.shell = ShellExecutor()

    def execute(self, pattern: str) -> ToolResult:
        result = self.shell.run_args(["ugrep", "-rn", pattern, "."], cwd=self.worktree_path)
        output = result.stdout.strip() or _no_output(result.stdout, result.stderr)
        return self.format_result(output)


class AstGrepTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("ast_grep", "ast-grep structural search (Python only, AST-aware)")
        self.worktree_path = worktree_path
        self.shell = ShellExecutor()

    def execute(self, pattern: str) -> ToolResult:
        result = self.shell.run_args(
            ["ast-grep", "run", "--pattern", pattern, "--lang", "python", "--json", "."],
            cwd=self.worktree_path,
        )

        if not result.stdout.strip():
            if result.stderr.strip():
                return self.format_result(f"Error: {result.stderr.strip()}")
            return self.format_result("No matches found.")

        try:
            data = json.loads(result.stdout)
            if not data:
                return self.format_result("No matches found.")

            formatted = []
            for match in data:
                path = match.get("file", "")
                line = match.get("range", {}).get("start", {}).get("line", 0) + 1
                text = match.get("text", "").strip()
                formatted.append(f"{path}:{line}:{text}")

            return self.format_result("\n".join(formatted))
        except json.JSONDecodeError:
            return self.format_result(result.stdout.strip())


class SemgrepTool(BaseTool):
    """Legacy tool - semgrep >= 1.100 requires login to show matched code lines."""

    def __init__(self, worktree_path: str):
        super().__init__("semgrep", "Semgrep structural search (Python only)")
        self.worktree_path = worktree_path
        self.shell = ShellExecutor()

    def execute(self, pattern: str) -> ToolResult:
        result = self.shell.run_args(
            ["semgrep", "--lang", "python", "--pattern", pattern,
             "--include", "*.py", "--json", "--quiet", "."],
            cwd=self.worktree_path,
        )

        if not result.stdout.strip():
            if result.stderr:
                return self.format_result(result.stderr.strip())
            return self.format_result("No matches found.")

        try:
            data = json.loads(result.stdout)
            results = data.get("results", [])
            if not results:
                return self.format_result("No matches found.")

            formatted = []
            for r in results:
                path = r.get("path")
                line = r.get("start", {}).get("line")
                content = r.get("extra", {}).get("lines", "").strip()
                formatted.append(f"{path}:{line}:{content}")

            return self.format_result("\n".join(formatted))
        except json.JSONDecodeError:
            return self.format_result(result.stdout.strip())
