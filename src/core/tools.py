from typing import Protocol

import tiktoken
from pydantic import BaseModel


class ToolResult(BaseModel):
    """
    Result of a tool execution.
    """
    output: str
    tokens: int


class Tool(Protocol):
    """
    Protocol for all tools in the benchmark.
    """
    name: str
    description: str

    def execute(self, **kwargs) -> ToolResult:
        ...


class BaseTool:
    """
    Base class for all tools with token counting utilities.
    """
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        # Try tiktoken; fall back to char-based estimate if encoding unavailable
        # (tiktoken 0.13+ moved encodings to a plugin architecture)
        try:
            self._tokenizer = tiktoken.get_encoding("cl100k_base")
        except (ValueError, Exception):
            self._tokenizer = None

    def count_tokens(self, text: str) -> int:
        """Counts tokens in the given text."""
        if not text:
            return 0
        if self._tokenizer is not None:
            return len(self._tokenizer.encode(text))
        return max(1, len(text) // 4)

    def format_result(self, output: str) -> ToolResult:
        """Wraps output into ToolResult with token count."""
        return ToolResult(
            output=output,
            tokens=self.count_tokens(output)
        )
