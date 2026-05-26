from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.basic_tools import PatchApplierTool


class PatchValidator(BaseToolValidator):
    tool_name = "patch"
    cli_binary = "git"

    def _get_tool_instance(self, tmp_dir): return PatchApplierTool(tmp_dir)

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        tool = PatchApplierTool(tmp_dir)
        # Invalid patch should still run and return an error message, not crash
        result = tool.execute(patch="invalid patch")
        passed = "Error:" in str(result.output) or "failed" in str(result.output).lower()
        return ValidationResult(passed=passed, detail="Patch tool handled invalid input") 
