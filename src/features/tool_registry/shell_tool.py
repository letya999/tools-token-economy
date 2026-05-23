"""
Shell tool: executes arbitrary bash commands in the worktree context.
"""
from src.core.tools import BaseTool, ToolResult
from src.features.shell import ShellExecutor


class ShellTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("shell", "Runs a bash command in the repository directory")
        self.worktree_path = worktree_path
        self.executor = ShellExecutor()

    def execute(self, command: str, timeout: float = 30.0) -> ToolResult:
        result = self.executor.run(command, cwd=self.worktree_path, timeout=timeout)
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        if not output.strip():
            output = f"(exit code: {result.exit_code})"
        return self.format_result(output)
