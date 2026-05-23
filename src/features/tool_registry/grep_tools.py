import shlex
from src.core.tools import BaseTool, ToolResult
from src.features.shell import ShellExecutor

class GrepTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("grep", "Standard recursive grep search")
        self.worktree_path = worktree_path
        self.shell = ShellExecutor()

    def execute(self, pattern: str) -> ToolResult:
        # -n line numbers, -r recursive, -I ignore binary files
        safe_pattern = shlex.quote(pattern)
        # Handle cross-platform: Windows powershell natively handles grep as an alias sometimes, 
        # but in WSL2 or native *nix it's the actual binary.
        # Since requirements state WSL2 compatibility, we assume standard grep flags.
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
