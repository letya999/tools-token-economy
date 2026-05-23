import os
from typing import List, Optional
from src.core.tools import BaseTool, ToolResult
from src.features.mcp_client import McpToolClient

# Optional import for BM25 fallback
try:
    from rank_bm25 import BM25Okapi
    HAS_BM25 = True
except ImportError:
    HAS_BM25 = False

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
        if not HAS_BM25:
            return self.format_result("Error: rank_bm25 not installed. RAG fallback unavailable.")

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
            except Exception:
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
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    snippet = f.read(500).strip()
                results.append(f"FILE: {rel_path}\nSNIPPET: {snippet}...")
            except Exception:
                continue

        output = "\n\n".join(results) if results else "No relevant files found."
        return self.format_result(output)

class SerenaAdapterTool(BaseTool):
    """
    Инструмент для семантического поиска (Serena). 
    Использует персистентный MCP-клиент.
    """
    def __init__(self, worktree_path: str):
        super().__init__("serena", "Semantic retrieval for codebase using Serena MCP")
        self.worktree_path = worktree_path
        self.rag_engine = SimpleRagTool(worktree_path)
        self._client: Optional[McpToolClient] = None

    def _get_client(self) -> McpToolClient:
        if self._client is None:
            # Prefer 'serena' command if available, else use uvx
            self._client = McpToolClient(
                server_command="serena",
                server_args=["start-mcp-server", "--project", self.worktree_path],
            )
        return self._client

    def execute(self, query: str) -> ToolResult:
        try:
            client = self._get_client()
            result = client.call_tool("find_symbol", {"query": query})
            return self.format_result(result)
        except Exception:
            # Fallback to simple RAG
            return self.rag_engine.execute(query=query)

    def close(self):
        if self._client:
            self._client.close()
            self._client = None

    def __del__(self):
        self.close()

class SembleAdapterTool(BaseTool):
    """
    Инструмент для структурной навигации (Semble).
    """
    def __init__(self, worktree_path: str):
        super().__init__("semble", "Structural navigation using Semble MCP")
        self.worktree_path = worktree_path
        self.rag_engine = SimpleRagTool(worktree_path)
        self._client: Optional[McpToolClient] = None

    def _get_client(self) -> McpToolClient:
        if self._client is None:
            # Semble might be installed via npm/pip or accessible via its own CLI
            self._client = McpToolClient(
                server_command="semble",
                server_args=["mcp", "--path", self.worktree_path],
            )
        return self._client

    def execute(self, action: str = "map", query: str = "") -> ToolResult:
        try:
            client = self._get_client()
            tool_name = "get_symbols_overview" if action == "map" else "find_symbol"
            args = {"query": query} if query else {"path": self.worktree_path}
            result = client.call_tool(tool_name, args)
            return self.format_result(result)
        except Exception:
            return self.rag_engine.execute(query=query or action)

    def close(self):
        if self._client:
            self._client.close()
            self._client = None

    def __del__(self):
        self.close()
