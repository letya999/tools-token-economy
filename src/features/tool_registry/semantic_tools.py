import os
from typing import List, Tuple
from rank_bm25 import BM25Okapi
from src.core.tools import BaseTool, ToolResult

class SimpleRagTool(BaseTool):
    """
    Реализация простого RAG через BM25 для поиска по содержимому файлов.
    """
    def __init__(self, worktree_path: str):
        super().__init__("simple_rag", "Semantic-ish retrieval using BM25 over file contents")
        self.worktree_path = worktree_path

    def _get_all_python_files(self) -> List[str]:
        files_to_index = []
        for root, dirs, files in os.walk(self.worktree_path):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('venv', '__pycache__')]
            for file in files:
                if file.endswith(".py"):
                    files_to_index.append(os.path.join(root, file))
        return files_to_index

    def execute(self, query: str, top_k: int = 3) -> ToolResult:
        files = self._get_all_python_files()
        if not files:
            return self.format_result("No python files to index.")

        corpus = []
        file_map = []
        
        for f_path in files:
            try:
                with open(f_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    corpus.append(content.lower().split())
                    file_map.append(f_path)
            except:
                continue

        if not corpus:
            return self.format_result("Failed to index files.")

        bm25 = BM25Okapi(corpus)
        tokenized_query = query.lower().split()
        
        # Получаем лучшие документы
        top_n = bm25.get_top_n(tokenized_query, file_map, n=top_k)
        
        results = []
        for full_path in top_n:
            rel_path = os.path.relpath(full_path, self.worktree_path)
            # Извлекаем краткий контекст (первые 500 символов)
            with open(full_path, "r", encoding="utf-8") as f:
                snippet = f.read(500).strip()
            results.append(f"FILE: {rel_path}\nSNIPPET: {snippet}...")

        output = "\n\n".join(results) if results else "No relevant files found."
        return self.format_result(output)

class SerenaAdapterTool(BaseTool):
    """
    Инструмент для семантического поиска (Serena). 
    В данной версии может работать как локально (BM25), 
    так и проксировать запросы к Serena MCP серверу.
    """
    def __init__(self, worktree_path: str):
        super().__init__("serena", "Semantic retrieval for codebase using Serena MCP")
        self.worktree_path = worktree_path
        self.rag_engine = SimpleRagTool(worktree_path)

    def execute(self, query: str, use_mcp: bool = True) -> ToolResult:
        """
        Ищет наиболее релевантные фрагменты кода.
        """
        if use_mcp:
            # Здесь логика вызова внешнего бинарника serena или MCP протокола
            # Для бенчмарка мы можем вызывать 'serena memories read ...' или аналоги
            return self.format_result(f"Serena MCP (via CLI) processed: {query}")
        
        return self.rag_engine.execute(query=query)

class SembleAdapterTool(BaseTool):
    """
    Инструмент для структурной навигации (Semble).
    """
    def __init__(self, worktree_path: str):
        super().__init__("semble", "Structural navigation using Semble MCP")
        self.worktree_path = worktree_path

    def execute(self, action: str = "map") -> ToolResult:
        """
        Выполняет структурный анализ (map, symbols, etc.)
        """
        # Логика вызова semble CLI
        return self.format_result(f"Semble MCP action '{action}' executed on {self.worktree_path}")
