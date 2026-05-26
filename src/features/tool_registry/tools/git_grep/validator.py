from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.grep_tools import GitGrepTool


class GitGrepValidator(BaseToolValidator):
    tool_name = "git_grep"
    cli_binary = "git"
    def _get_tool_instance(self, tmp_dir): return GitGrepTool(tmp_dir)
