import os

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Query, QueryCursor

from src.core.tools import BaseTool, ToolResult


class TreeSitterTool(BaseTool):
    """Extracts function and class symbols from a Python file via Tree-Sitter AST."""

    def __init__(self, worktree_path: str):
        super().__init__(
            "tree_sitter",
            "Extracts function and class names with line numbers from a Python file via AST. "
            "Requires a known file path — use read tool first to discover candidate files. "
            "Example: tree_sitter('app/services/admin_auth.py') lists all functions defined there. "
            "Workflow: (1) use read to explore directories like 'app/', 'src/' to find Python files, "
            "(2) call tree_sitter on candidate files to see their structure.",
        )
        self.worktree_path = worktree_path
        self.PY_LANGUAGE = Language(tspython.language())
        self.parser = Parser(self.PY_LANGUAGE)

    def execute(self, file_path: str) -> ToolResult:
        full_path = self._safe_path(self.worktree_path, file_path)
        if full_path is None:
            return self.format_result(f"Access denied: {file_path}")
        if not os.path.isfile(full_path):
            return self.format_result(f"Error: File not found: {file_path}")

        try:
            with open(full_path, "rb") as f:
                content = f.read()

            tree = self.parser.parse(content)
            # Extract only top-level symbols (functions, classes) to keep token count low
            symbols = []

            query_str = """
                (function_definition name: (identifier) @func.name)
                (class_definition name: (identifier) @class.name)
            """
            query = Query(self.PY_LANGUAGE, query_str)
            cursor = QueryCursor(query)

            captures = cursor.captures(tree.root_node)
            for tag, nodes in captures.items():
                for node in nodes:
                    line_num = node.start_point[0] + 1
                    name = content[node.start_byte:node.end_byte].decode('utf-8')
                    symbols.append(f"{tag}: {name} (line {line_num})")

            output = "\n".join(symbols) if symbols else "No major symbols found."
            return self.format_result(output)
        except Exception as e:
            return self.format_result(f"Error parsing file: {e}")

class RepoMapTool(BaseTool):
    """Generates a map of the repository: files with their key symbols."""

    def __init__(self, worktree_path: str):
        super().__init__("repo_map", "Generates a map of the repository with files and symbols")
        self.worktree_path = worktree_path
        self.ts_tool = TreeSitterTool(worktree_path)

    def execute(self) -> ToolResult:
        repo_map = []

        for root, dirs, files in os.walk(self.worktree_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('venv', '__pycache__', 'node_modules')]

            rel_root = os.path.relpath(root, self.worktree_path)
            if rel_root == ".":
                rel_root = ""

            for file in files:
                if file.endswith(".py"):
                    rel_path = os.path.join(rel_root, file)
                    symbols_res = self.ts_tool.execute(rel_path)
                    symbols_content = "  " + symbols_res.output.replace("\n", "\n  ")
                    repo_map.append(f"FILE: {rel_path}\n{symbols_content}")
                elif not file.startswith("."):
                    repo_map.append(f"FILE: {os.path.join(rel_root, file)}")

        output = "\n\n".join(repo_map)
        return self.format_result(output)
