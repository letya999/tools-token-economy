from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.basic_tools import ReadAllTool


class ReadAllValidator(BaseToolValidator):
    tool_name = "read_all"
    def _get_tool_instance(self, tmp_dir): return ReadAllTool(tmp_dir)
