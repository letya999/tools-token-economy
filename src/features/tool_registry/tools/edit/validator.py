from src.features.tool_registry.base import BaseToolValidator
from src.features.tool_registry.basic_tools import StrReplaceEditTool


class EditValidator(BaseToolValidator):
    tool_name = "edit"
    def _get_tool_instance(self, tmp_dir): return StrReplaceEditTool(tmp_dir)
