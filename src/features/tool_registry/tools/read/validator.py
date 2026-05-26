from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.basic_tools import FileReadTool


class ReadValidator(BaseToolValidator):
    tool_name = "read"
    cli_binary = None

    def _get_tool_instance(self, tmp_dir): return FileReadTool(tmp_dir)

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        tool = FileReadTool(tmp_dir)
        # Seeded file name is smoke_test_file.txt (from Doctor.check_all)
        result = tool.execute(file_path="smoke_test_file.txt")
        passed = "Error:" not in str(result.output)
        return ValidationResult(passed=passed, detail=str(result.output)[:100])
 
