from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.grep_tools import AstGrepTool


class AstGrepValidator(BaseToolValidator):
    tool_name = "ast_grep"
    cli_binary = "ast-grep"
    platform_install_cmds = {
        "linux": "cargo install ast-grep --locked",
        "wsl": "cargo install ast-grep --locked",
        "mac": "brew install ast-grep",
        "windows": "winget install ast-grep",
    }
    def _get_tool_instance(self, tmp_dir): return AstGrepTool(tmp_dir)
