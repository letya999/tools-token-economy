from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.grep_tools import AstGrepTool


class AstGrepValidator(BaseToolValidator):
    tool_name = "ast_grep"
    cli_binary = "ast-grep"
    def _get_tool_instance(self, tmp_dir): return AstGrepTool(tmp_dir)
