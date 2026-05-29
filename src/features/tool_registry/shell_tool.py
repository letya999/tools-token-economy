"""
Shell tool: executes arbitrary bash commands in the worktree context.
"""
from src.core.tools import BaseTool, ToolResult
from src.features.shell import ShellExecutor


class ShellTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("shell", "Runs one or more shell commands in the repository directory")
        self.worktree_path = worktree_path
        self.executor = ShellExecutor()

    def execute(self, command: str | None = None, multi_cmd: list[str] | None = None, timeout: float = 30.0) -> ToolResult:
        if not command and not multi_cmd:
            return self.format_result("Error: No command provided")
        
        cmds = multi_cmd if multi_cmd else [command]
        # Security: block obvious disaster commands
        blocked = ["rm -rf /", "rm -rf *", "rm -rf .", ":(){ :|:& };:"]
        for c in cmds:
            if any(b in c for b in blocked):
                return self.format_result(f"Error: Command '{c}' is blocked for security reasons.")

        full_output = []
        for c in cmds:
            result = self.executor.run(c, cwd=self.worktree_path, timeout=timeout)
            out = f"$ {c}\n{result.stdout}"
            if result.stderr:
                out += f"\nSTDERR:\n{result.stderr}"
            if result.exit_code != 0 or not result.stdout.strip():
                out += f"\n(exit code: {result.exit_code})"
            full_output.append(out)
        
        _MAX_SHELL_OUTPUT = 2_000
        combined = "\n\n".join(full_output)
        if len(combined) > _MAX_SHELL_OUTPUT:
            combined = combined[:_MAX_SHELL_OUTPUT] + f"\n\n[OUTPUT TRUNCATED: shell output exceeded {_MAX_SHELL_OUTPUT} chars]"
        return self.format_result(combined)
