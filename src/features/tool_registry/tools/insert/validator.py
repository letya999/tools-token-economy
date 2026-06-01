from src.features.tool_registry.base import BaseToolValidator
from src.features.tool_registry.basic_tools import InsertAfterLineTool


class InsertValidator(BaseToolValidator):
    tool_name = "insert"
    def _get_tool_instance(self, tmp_dir): return InsertAfterLineTool(tmp_dir)
