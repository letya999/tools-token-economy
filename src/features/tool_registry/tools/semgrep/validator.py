from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.grep_tools import SemgrepTool


class SemgrepValidator(BaseToolValidator):
    tool_name = "semgrep"
    cli_binary = "semgrep"
    def _get_tool_instance(self, tmp_dir): return SemgrepTool(tmp_dir)
