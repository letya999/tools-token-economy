from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.basic_tools import FileWriteTool


class WriteValidator(BaseToolValidator):
    tool_name = "write"
    cli_binary = None

    def _get_tool_instance(self, tmp_dir): return FileWriteTool(tmp_dir)

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        tool = FileWriteTool(tmp_dir)
        result = tool.execute(file_path="smoke_write.txt", content="hello")
        passed = "Error:" not in str(result.output)
        return ValidationResult(passed=passed, detail=str(result.output)[:100]) 
