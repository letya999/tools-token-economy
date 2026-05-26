from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.lsp_tools import LspSymbolsTool


class LspSymbolsValidator(BaseToolValidator):
    tool_name = "lsp_symbols"
    def _get_tool_instance(self, tmp_dir): return LspSymbolsTool(tmp_dir)
