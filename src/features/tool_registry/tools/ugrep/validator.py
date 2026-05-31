from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.grep_tools import UgrepTool


class UgrepValidator(BaseToolValidator):
    tool_name = "ugrep"
    cli_binary = "ugrep"
    platform_install_cmds = {
        "linux": "sudo apt-get install -y ugrep",
        "wsl": "sudo apt-get install -y ugrep",
        "mac": "brew install ugrep",
        "windows": "winget install Genivia.ugrep",
    }
    def _get_tool_instance(self, tmp_dir): return UgrepTool(tmp_dir)
