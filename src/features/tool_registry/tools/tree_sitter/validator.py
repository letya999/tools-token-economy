from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.structural_tools import TreeSitterTool


class TreeSitterValidator(BaseToolValidator):
    tool_name = "tree_sitter"
    def _get_tool_instance(self, tmp_dir): return TreeSitterTool(tmp_dir)
