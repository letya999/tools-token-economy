"""
Base infrastructure for tool validation.
"""
import subprocess
import shutil
import logging
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    passed: bool
    detail: str = ""
    skipped: bool = False


class BaseToolValidator:
    """
    Base class for validating a tool's availability and correctness.
    """
    tool_name: str = ""
    cli_binary: str | None = None
    platform_install_cmds: dict[str, str] = {}  # platform -> cmd

    def check_installed(self) -> ValidationResult:
        """Check if the required CLI binary or Python package is present."""
        if self.cli_binary:
            if shutil.which(self.cli_binary):
                return ValidationResult(passed=True, detail=f"Binary '{self.cli_binary}' found.")
            return ValidationResult(passed=False, detail=f"Binary '{self.cli_binary}' NOT found.")
        return ValidationResult(passed=True, detail="No CLI binary required.")

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        """Run a minimal execution of the tool to verify it works."""
        return ValidationResult(passed=True, detail="smoke test not implemented")

    def validate_agno_registration(self, tmp_dir: str) -> ValidationResult:
        """Verify the tool can be wrapped and seen by an Agno agent."""
        try:
            from agno.agent import Agent
            from agno.tools import tool as agno_tool
            import inspect

            tool_instance = self._get_tool_instance(tmp_dir)
            if not tool_instance:
                return ValidationResult(passed=False, detail="Failed to instantiate tool for Agno check")

            # Minimal Agno wrapper logic (similar to AgnoRunner)
            sig = inspect.signature(tool_instance.execute)
            globs = {"_tool": tool_instance}
            args = [f"{n}={n}" for n in sig.parameters]
            params = []
            for n, p in sig.parameters.items():
                if p.default is inspect.Parameter.empty:
                    params.append(f"{n}: str")
                else:
                    params.append(f"{n}: str = {repr(p.default)}")

            src = (
                f"def {tool_instance.name}({', '.join(params)}) -> str:\n"
                f"    return _tool.execute({', '.join(args)}).output\n"
            )
            exec(src, globs)
            fn = globs[tool_instance.name]
            fn.__doc__ = tool_instance.description
            wrapped = agno_tool(fn)

            # Create agent and check tool appears
            agent = Agent(tools=[wrapped], markdown=False)
            tool_names = [t.name if hasattr(t, 'name') else str(t) for t in (agent.tools or [])]

            if tool_instance.name in str(tool_names):
                return ValidationResult(passed=True, detail=f"Tool '{tool_instance.name}' registered in Agno agent")
            return ValidationResult(passed=False, detail=f"Tool '{tool_instance.name}' NOT found in agent.tools: {tool_names}")
        except Exception as e:
            return ValidationResult(passed=False, detail=f"Agno registration check failed: {e}")

    def _get_tool_instance(self, tmp_dir: str):
        """Override in subclass to return the actual tool instance for this validator."""
        return None

    def configure(self, repo_path: str) -> ValidationResult:
        """One-time configuration (e.g., create .serena/project.yml)."""        
        return ValidationResult(passed=True, detail="no configuration needed")  

    def prepare(self, repo_path: str) -> ValidationResult:
        """Expensive one-time preparation (e.g., RAG ingestion, repo map build)."""
        return ValidationResult(passed=True, detail="no preparation needed")    

    def install(self, platform: str) -> ValidationResult:
        """Attempt to install the tool on the given platform."""
        cmd = self.platform_install_cmds.get(platform)
        if not cmd:
            return ValidationResult(
                passed=False,
                detail=f"No install command defined for platform '{platform}'. Install '{self.cli_binary}' manually."
            )
        try:
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
            if proc.returncode == 0:
                return ValidationResult(passed=True, detail=f"Installed via: {cmd}")
            return ValidationResult(passed=False, detail=f"Install failed (exit {proc.returncode}): {proc.stderr.strip()[:200]}")
        except Exception as e:
            return ValidationResult(passed=False, detail=f"Install error: {e}") 
