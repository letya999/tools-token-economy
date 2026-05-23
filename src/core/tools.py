from typing import Protocol, Any
from pydantic import BaseModel
import tiktoken

class ToolResult(BaseModel):
    output: str
    token_count: int

class BaseTool:
    """
    Базовый класс для всех инструментов с утилитами для подсчета токенов.
    """
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        # Используем стандартный энкодер (например, от GPT-4/3.5) как прокси 
        # для универсального бенчмарка, если нет специфичного для Gemini.
        self._tokenizer = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        """Считает количество токенов в строке."""
        if not text:
            return 0
        return len(self._tokenizer.encode(text))

    def format_result(self, output: str) -> ToolResult:
        """Оборачивает вывод в ToolResult с подсчетом токенов."""
        return ToolResult(
            output=output,
            token_count=self.count_tokens(output)
        )

class Tool(Protocol):
    name: str
    description: str
    def execute(self, **kwargs) -> ToolResult:
        ...
