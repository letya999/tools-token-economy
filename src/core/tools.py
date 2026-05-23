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
        # Standard tokenizer (e.g. GPT-4/3.5) as a proxy for universal benchmarking
        self._tokenizer = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        """Counts tokens in the given text."""
        if not text:
            return 0
        return len(self._tokenizer.encode(text))

    def format_result(self, output: str) -> ToolResult:
        """Wraps output into ToolResult with token count."""
        return ToolResult(
            output=output,
            tokens=self.count_tokens(output)
        )
