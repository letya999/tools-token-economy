import subprocess
from dataclasses import dataclass


@dataclass
class ShellResult:
    stdout: str
    stderr: str
    exit_code: int

class ShellExecutor:
    """
    Executes shell commands and returns the results.
    """
    def run(self, command: str, cwd: str | None = None, timeout: float | None = None, env: dict | None = None) -> ShellResult:
        try:
            process = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=env,
            )
            return ShellResult(
                stdout=process.stdout,
                stderr=process.stderr,
                exit_code=process.returncode
            )
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(f"Command '{command}' timed out after {timeout} seconds") from e
        except Exception as e:
            return ShellResult(
                stdout="",
                stderr=str(e),
                exit_code=1
            )

    def run_args(self, args: list[str], cwd: str | None = None, timeout: float | None = None, env: dict | None = None) -> ShellResult:
        """Run a command from a list of arguments without a shell intermediary.

        Bypasses all shell quoting issues — safe on both Windows and POSIX.
        """
        try:
            process = subprocess.run(
                args,
                shell=False,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=env,
            )
            return ShellResult(
                stdout=process.stdout,
                stderr=process.stderr,
                exit_code=process.returncode,
            )
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(f"Command '{args[0]}' timed out after {timeout} seconds") from e
        except Exception as e:
            return ShellResult(stdout="", stderr=str(e), exit_code=1)
