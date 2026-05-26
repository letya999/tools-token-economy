from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.basic_tools import GlobTool


class GlobValidator(BaseToolValidator):
    tool_name = "glob"
    def _get_tool_instance(self, tmp_dir): return GlobTool(tmp_dir)
