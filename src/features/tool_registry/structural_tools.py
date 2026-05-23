import os
import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Query, QueryCursor
from src.core.tools import BaseTool, ToolResult

class TreeSitterTool(BaseTool):
    """
    Инструмент для извлечения структуры файла через AST (Tree-Sitter).
    """
    def __init__(self, worktree_path: str):
        super().__init__("tree_sitter", "Extracts AST structure from a file (Python only for now)")
        self.worktree_path = worktree_path
        self.PY_LANGUAGE = Language(tspython.language())
        self.parser = Parser(self.PY_LANGUAGE)

    def execute(self, file_path: str) -> ToolResult:
        full_path = os.path.join(self.worktree_path, file_path)
        if not os.path.isfile(full_path):
            return self.format_result(f"Error: File not found: {file_path}")

        try:
            with open(full_path, "rb") as f:
                content = f.read()

            tree = self.parser.parse(content)
            # Извлекаем только важные узлы (функции, классы) для экономии токенов
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
    """
    Создает карту репозитория: список файлов и их ключевых символов.
    """
    def __init__(self, worktree_path: str):
        super().__init__("repo_map", "Generates a map of the repository with files and symbols")
        self.worktree_path = worktree_path
        self.ts_tool = TreeSitterTool(worktree_path)

    def execute(self, depth: int = 2) -> ToolResult:
        repo_map = []
        
        for root, dirs, files in os.walk(self.worktree_path):
            # Пропускаем скрытые папки и venv
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('venv', '__pycache__')]
            
            rel_root = os.path.relpath(root, self.worktree_path)
            if rel_root == ".":
                rel_root = ""

            for file in files:
                if file.endswith(".py"):
                    rel_path = os.path.join(rel_root, file)
                    symbols_res = self.ts_tool.execute(rel_path)
                    
                    file_header = f"FILE: {rel_path}"
                    symbols_content = "  " + symbols_res.output.replace("\n", "\n  ")
                    repo_map.append(f"{file_header}\n{symbols_content}")
                elif not file.startswith("."):
                    # Просто фиксируем наличие не-python файлов
                    repo_map.append(f"FILE: {os.path.join(rel_root, file)}")

        output = "\n\n".join(repo_map)
        return self.format_result(output)
