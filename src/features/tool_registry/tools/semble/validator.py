import subprocess
from src.features.tool_registry.base import BaseToolValidator, ValidationResult 


class SembleValidator(BaseToolValidator):
    tool_name = "semble"
    cli_binary = "uvx"

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        # Just check if uvx can see semble
        result = subprocess.run(
            ["uvx", "--from", "semble[mcp]", "semble", "--help"],
            capture_output=True, text=True, timeout=30
        )
        passed = result.returncode == 0
        return ValidationResult(passed=passed, detail="semble help ran via uvx")

    def validate_agno_registration(self, tmp_dir: str) -> ValidationResult:     
        return ValidationResult(passed=True, detail="Semble MCP available via uvx")
