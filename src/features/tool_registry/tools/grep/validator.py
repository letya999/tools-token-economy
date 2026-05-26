from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.grep_tools import GrepTool


class GrepValidator(BaseToolValidator):
    tool_name = "grep"
    cli_binary = "grep"
    platform_install_cmds = {
        "linux": "sudo apt-get install -y grep",
        "wsl": "sudo apt-get install -y grep",
    }

    def _get_tool_instance(self, tmp_dir): return GrepTool(tmp_dir)

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        tool = GrepTool(tmp_dir)
        result = tool.execute(pattern="hello_world")
        passed = "Error:" not in str(result.output)
        return ValidationResult(passed=passed, detail=str(result.output)[:100]) 
