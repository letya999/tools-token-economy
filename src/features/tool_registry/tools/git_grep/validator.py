from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.grep_tools import GitGrepTool


class GitGrepValidator(BaseToolValidator):
    tool_name = "git_grep"
    cli_binary = "git"
    platform_install_cmds = {
        "linux": "sudo apt-get install -y git",
        "wsl": "sudo apt-get install -y git",
        "mac": "brew install git",
        "windows": "winget install Git.Git",
    }
    def _get_tool_instance(self, tmp_dir): return GitGrepTool(tmp_dir)
