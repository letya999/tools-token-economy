from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.basic_tools import InsertAfterTool


class InsertAfterValidator(BaseToolValidator):
    tool_name = "insert_after"
    def _get_tool_instance(self, tmp_dir): return InsertAfterTool(tmp_dir)
