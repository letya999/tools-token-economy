import os
import subprocess

from src.features.tool_registry.base import BaseToolValidator, ValidationResult

_WARMUP_FLAG = os.path.expanduser("~/.semble_warmed_up")


class SembleValidator(BaseToolValidator):
    tool_name = "semble"
    cli_binary = "uvx"

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        # First-time uvx download can take 2-3 minutes. Use a longer timeout until
        # the setup script marks completion via ~/.semble_warmed_up.
        warmed_up = os.path.exists(_WARMUP_FLAG)
        timeout = 30 if warmed_up else 120
        try:
            result = subprocess.run(
                ["uvx", "--from", "semble[mcp]", "semble", "--help"],
                capture_output=True, text=True, timeout=timeout
            )
            passed = result.returncode == 0
            detail = "semble help ran via uvx" if passed else f"semble failed: {result.stderr[:100]}"
            return ValidationResult(passed=passed, detail=detail)
        except subprocess.TimeoutExpired:
            hint = "run `uv tool install semble` to pre-warm" if not warmed_up else "try re-running setup_serena_semble.sh"
            return ValidationResult(
                passed=False,
                detail=f"semble timed out after {timeout}s — {hint}"
            )

    def validate_agno_registration(self, tmp_dir: str) -> ValidationResult:
        return ValidationResult(passed=True, detail="Semble MCP available via uvx")
