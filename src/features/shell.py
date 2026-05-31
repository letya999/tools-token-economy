import shutil
import subprocess
import sys
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
    @staticmethod
    def _effective_shell() -> str | None:
        """Return the shell executable for shell=True, or None for default."""
        if sys.platform != "win32":
            return None  # subprocess uses /bin/sh by default on POSIX
            
        import shutil
        # If 'bash' is already in PATH and working, just use 'bash'
        if shutil.which("bash"):
            return "bash"
            
        # Otherwise look for common Git Bash location
        git_bash = "C:\\Program Files\\Git\\bin\\bash.exe"
        if shutil.which(git_bash):
            return git_bash
            
        return None  # falls back to cmd.exe

    def run(self, command: str, cwd: str | None = None, timeout: float | None = None, env: dict | None = None) -> ShellResult:
        executable = self._effective_shell()
        
        # If we have a potential shell candidate (like bash), try it first
        if executable:
            try:
                # IMPORTANT: On Windows, 'executable' with shell=True is tricky.
                # We only use it if it's a simple command name like 'bash' 
                # or if it has no spaces to avoid WinError 123/127.
                process = subprocess.run(
                    command,
                    shell=True,
                    executable=executable if " " not in executable else None,
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
            except (OSError, subprocess.SubprocessError):
                # If bash attempt failed to even start, fallback to default shell
                pass

        try:
            # Default fallback (cmd.exe on Windows, /bin/sh on POSIX)
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
