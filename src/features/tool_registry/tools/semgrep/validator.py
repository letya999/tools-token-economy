from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.grep_tools import SemgrepTool


class SemgrepValidator(BaseToolValidator):
    tool_name = "semgrep"
    cli_binary = "semgrep"
    platform_install_cmds = {
        "linux": "pip install semgrep",
        "wsl": "pip install semgrep",
        "mac": "brew install semgrep",
        "windows": "pip install semgrep",
    }
    def _get_tool_instance(self, tmp_dir): return SemgrepTool(tmp_dir)
