from src.features.tool_registry.base import BaseToolValidator
from src.features.tool_registry.basic_tools import AppendToFileTool


class AppendValidator(BaseToolValidator):
    tool_name = "append"
    def _get_tool_instance(self, tmp_dir): return AppendToFileTool(tmp_dir)
