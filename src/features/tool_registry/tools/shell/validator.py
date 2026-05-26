from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.shell_tool import ShellTool


class ShellValidator(BaseToolValidator):
    tool_name = "shell"
    cli_binary = None # Uses system shell

    def _get_tool_instance(self, tmp_dir): return ShellTool(tmp_dir)

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        tool = ShellTool(tmp_dir)
        result = tool.execute(command="echo hello")
        passed = "hello" in str(result.output)
        return ValidationResult(passed=passed, detail=str(result.output)[:100]) 
