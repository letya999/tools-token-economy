from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.grep_tools import RgTool


class RgValidator(BaseToolValidator):
    tool_name = "rg"
    cli_binary = "rg"
    platform_install_cmds = {
        "linux": "sudo apt-get install -y ripgrep",
        "wsl": "sudo apt-get install -y ripgrep",
        "mac": "brew install ripgrep",
        "windows": "winget install BurntSushi.ripgrep.MSVC",
    }

    def _get_tool_instance(self, tmp_dir): return RgTool(tmp_dir)

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        tool = RgTool(tmp_dir)
        result = tool.execute(pattern="hello_world")
        passed = "Error:" not in str(result.output)
        return ValidationResult(passed=passed, detail=str(result.output)[:100]) 
