from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.basic_tools import FileReadTool


class ReadValidator(BaseToolValidator):
    tool_name = "read"
    cli_binary = None

    def _get_tool_instance(self, tmp_dir): return FileReadTool(tmp_dir)

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        tool = FileReadTool(tmp_dir)
        # Try to read a file that might exist
        import os
        test_file = os.path.join(tmp_dir, "test_smoke.py")
        result = tool.execute(file_path="test_smoke.py")
        passed = "Error:" not in str(result.output)
        return ValidationResult(passed=passed, detail=str(result.output)[:100]) 
