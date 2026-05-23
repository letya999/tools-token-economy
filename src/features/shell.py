import subprocess
from dataclasses import dataclass
from typing import Optional

@dataclass
class ShellResult:
    stdout: str
    stderr: str
    exit_code: int

class ShellExecutor:
    """
    Executes shell commands and returns the results.
    """
    def run(self, command: str, cwd: Optional[str] = None, timeout: Optional[float] = None) -> ShellResult:
        try:
            process = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return ShellResult(
                stdout=process.stdout,
                stderr=process.stderr,
                exit_code=process.returncode
            )
        except subprocess.TimeoutExpired:
            raise TimeoutError(f"Command '{command}' timed out after {timeout} seconds")
        except Exception as e:
            return ShellResult(
                stdout="",
                stderr=str(e),
                exit_code=1
            )
