import subprocess
from src.features.tool_registry.base import BaseToolValidator, ValidationResult 


class SerenaValidator(BaseToolValidator):
    tool_name = "serena"
    cli_binary = "serena"
    platform_install_cmds = {
        "linux": "uv tool install serena",
        "wsl": "uv tool install serena",
        "windows": "uv tool install serena",
        "mac": "uv tool install serena",
    }

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        result = subprocess.run(
            ["serena", "--version"],
            capture_output=True, text=True, timeout=10
        )
        passed = result.returncode == 0
        return ValidationResult(passed=passed, detail=(result.stdout or result.stderr).strip()[:100])

    def configure(self, repo_path: str) -> ValidationResult:
        """Create minimal .serena/project.yml to avoid 4-min LSP startup."""    
        import os, yaml
        serena_dir = os.path.join(repo_path, ".serena")
        config_path = os.path.join(serena_dir, "project.yml")
        if os.path.isfile(config_path):
            return ValidationResult(passed=True, detail="already configured")   
        os.makedirs(serena_dir, exist_ok=True)
        project_cfg = {
            "project_name": os.path.basename(repo_path),
            "languages": ["python"],
            "encoding": "utf-8",
            "read_only": False,
            "excluded_tools": [],
            "included_optional_tools": [],
            "fixed_tools": [],
            "ignored_paths": [],
        }
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(project_cfg, f, default_flow_style=False)
        return ValidationResult(passed=True, detail=f"Created {config_path}")   

    def validate_agno_registration(self, tmp_dir: str) -> ValidationResult:     
        """For MCP tools, just verify the binary starts without error."""       
        result = self.smoke_test(tmp_dir)
        if result.passed:
            return ValidationResult(passed=True, detail="Serena MCP binary available (full MCP session test requires target repo)")
        return result
