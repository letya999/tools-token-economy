from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.grep_tools import UgrepTool


class UgrepValidator(BaseToolValidator):
    tool_name = "ugrep"
    cli_binary = "ugrep"
    def _get_tool_instance(self, tmp_dir): return UgrepTool(tmp_dir)
