import os
import glob
from src.core.tools import BaseTool, ToolResult
from src.features.patch import PatchApplier

class FileReadTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("read", "Reads content of a specific file")
        self.worktree_path = worktree_path

    def execute(self, file_path: str, start_line: int = 1, end_line: int = -1) -> ToolResult:
        full_path = os.path.join(self.worktree_path, file_path)
        if not os.path.isfile(full_path):
            return self.format_result(f"Error: File not found: {file_path}")
            
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            if start_line < 1:
                start_line = 1
            if end_line == -1 or end_line > len(lines):
                end_line = len(lines)
                
            selected_lines = lines[start_line - 1 : end_line]
            output = "".join(selected_lines)
            return self.format_result(output)
        except Exception as e:
            return self.format_result(f"Error reading file: {e}")

class ReadAllTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("read_all", "Reads all files in the repository (Caution: high tokens!)")
        self.worktree_path = worktree_path

    def execute(self) -> ToolResult:
        output = []
        for root, dirs, files in os.walk(self.worktree_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('venv', '__pycache__')]
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), self.worktree_path)
                try:
                    with open(os.path.join(root, file), "r", encoding="utf-8") as f:
                        content = f.read()
                        output.append(f"--- FILE: {rel_path} ---\n{content}")
                except:
                    continue
        return self.format_result("\n\n".join(output))

class FileWriteTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("write", "Writes complete content to a file")
        self.worktree_path = worktree_path

    def execute(self, file_path: str, content: str) -> ToolResult:
        full_path = os.path.join(self.worktree_path, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        try:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            return self.format_result(f"Successfully wrote to {file_path}")
        except Exception as e:
            return self.format_result(f"Error writing file: {e}")

class GlobTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("glob", "Finds files matching a glob pattern")
        self.worktree_path = worktree_path

    def execute(self, pattern: str) -> ToolResult:
        search_pattern = os.path.join(self.worktree_path, pattern)
        try:
            matches = glob.glob(search_pattern, recursive=True)
            rel_matches = [os.path.relpath(m, self.worktree_path) for m in matches]
            output = "\n".join(rel_matches)
            if not output:
                output = "No matches found."
            return self.format_result(output)
        except Exception as e:
            return self.format_result(f"Error globbing: {e}")

class PatchApplierTool(BaseTool):
    def __init__(self, worktree_path: str):
        super().__init__("patch", "Applies a git-style patch/diff")
        self.worktree_path = worktree_path
        self.applier = PatchApplier()

    def execute(self, patch: str) -> ToolResult:
        success = self.applier.apply(self.worktree_path, patch)
        if success:
            return self.format_result("Patch applied successfully.")
        else:
            return self.format_result("Error: Failed to apply patch.")
