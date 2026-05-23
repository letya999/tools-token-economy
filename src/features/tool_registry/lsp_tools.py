"""
LSP-like symbols tool using jedi for Python static analysis.
Provides symbol lookup without requiring a running language server.
"""
import os
import jedi
from src.core.tools import BaseTool, ToolResult


class LspSymbolsTool(BaseTool):
    """Extracts symbols and references using jedi static analysis."""

    def __init__(self, worktree_path: str):
        super().__init__("lsp_symbols", "LSP-like symbol lookup using jedi static analysis")
        self.worktree_path = worktree_path

    def execute(self, symbol: str = "", file_path: str = "") -> ToolResult:
        results = []
        project = jedi.Project(path=self.worktree_path)

        if file_path:
            full_path = os.path.join(self.worktree_path, file_path)
            if not os.path.isfile(full_path):
                return self.format_result(f"Error: File not found: {file_path}")
            try:
                # jedi >= 0.18: Script takes path only, reads file itself
                script = jedi.Script(path=full_path, project=project)
                names = script.get_names(definitions=True)
                for n in names:
                    results.append(f"{n.type}: {n.name} (line {n.line}, col {n.column})")
            except Exception as e:
                return self.format_result(f"Error analyzing {file_path}: {e}")
        elif symbol:
            # Project.search() finds names matching a string across the project
            try:
                for n in project.search(symbol):
                    module = getattr(n.module_path, "name", str(n.module_path)) if n.module_path else "?"
                    results.append(f"{module}: {n.type}: {n.name} (line {n.line})")
            except Exception:
                # Fallback: walk files manually
                for root, dirs, files in os.walk(self.worktree_path):
                    dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("venv", "__pycache__")]
                    for fname in files:
                        if not fname.endswith(".py"):
                            continue
                        fpath = os.path.join(root, fname)
                        try:
                            script = jedi.Script(path=fpath, project=project)
                            for n in script.get_names(definitions=True):
                                if n.name == symbol:
                                    rel = os.path.relpath(fpath, self.worktree_path)
                                    results.append(f"{rel}: {n.type}: {n.name} (line {n.line})")
                        except Exception:
                            continue
        else:
            return self.format_result("Provide either 'symbol' or 'file_path' argument.")

        output = "\n".join(results) if results else "No symbols found."
        return self.format_result(output)
