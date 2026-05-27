import os

from src.features.tool_registry.base import BaseToolValidator, ValidationResult
from src.features.tool_registry.structural_tools import TreeSitterTool


class TreeSitterValidator(BaseToolValidator):
    tool_name = "tree_sitter"

    def _get_tool_instance(self, tmp_dir):
        return TreeSitterTool(tmp_dir)

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        py_file = os.path.join(tmp_dir, "_ts_smoke.py")
        with open(py_file, "w") as f:
            f.write("def hello_world(): pass\nclass Foo: pass\n")
        try:
            tool = self._get_tool_instance(tmp_dir)
            result = tool.execute(file_path="_ts_smoke.py")
            if result.output.startswith("Error:"):
                return ValidationResult(passed=False, detail=result.output[:200])
            passed = "hello_world" in result.output or "Foo" in result.output
            detail = result.output[:80] if passed else f"unexpected output: {result.output[:200]}"
            return ValidationResult(passed=passed, detail=detail)
        except Exception as e:
            return ValidationResult(passed=False, detail=f"tree_sitter failed: {e}")
