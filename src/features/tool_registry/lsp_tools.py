from __future__ import annotations

import os

import jedi

from src.core.tools import BaseTool, ToolResult


class LspSymbolsTool(BaseTool):
    """
    Symbol analysis using Jedi static analysis.
    """

    def __init__(self, worktree_path: str):
        super().__init__("lsp_symbols", "Retrieve symbols/definitions using static analysis")
        self.worktree_path = os.path.realpath(worktree_path)

    def execute(self, symbol: str = "", file_path: str = "") -> ToolResult:
        """Entry point for symbol analysis."""
        if not symbol and not file_path:
            return self.format_result("Provide either 'symbol' or 'file_path' argument.")

        project = jedi.Project(path=self.worktree_path)
        if file_path:
            return self._analyze_file(file_path, project)
        return self._search_symbol(symbol, project)

    def _analyze_file(self, file_path: str, project: jedi.Project) -> ToolResult:
        """List all symbols in a file."""
        abs_path = self._safe_path(self.worktree_path, file_path)
        if abs_path is None:
            return self.format_result(f"Access denied: {file_path}")
        if not os.path.exists(abs_path):
            return self.format_result(f"File not found: {file_path}")

        try:
            script = jedi.Script(path=abs_path, project=project)
            names = script.get_names(definitions=True)
            results = [f"{n.type}: {n.name} (line {n.line}, col {n.column})" for n in names]
            return self.format_result("\n".join(results) if results else "No symbols found.")
        except Exception as e:
            return self.format_result(f"Error analyzing {file_path}: {e}")

    def _search_symbol(self, symbol: str, project: jedi.Project) -> ToolResult:
        """Search for a symbol in the project."""
        try:
            # Jedi search returns name objects with path info
            definitions = project.search(symbol)
            results = []
            for d in definitions:
                fpath = str(d.module_path) if d.module_path else "unknown"
                real_fpath = os.path.realpath(fpath)
                
                # Filter: must be inside worktree AND not in venv/site-packages
                is_inside = real_fpath.startswith(self.worktree_path + os.sep) or real_fpath == self.worktree_path
                is_external = ".venv" in real_fpath or "site-packages" in real_fpath
                
                if is_inside and not is_external:
                    rel = os.path.relpath(real_fpath, self.worktree_path)
                    results.append(f"Found symbol '{d.name}' in {rel} at line {d.line}")
            return self.format_result("\n".join(results) if results else f"Symbol '{symbol}' not found.")
        except Exception as e:
            return self.format_result(f"Search error: {e}")
