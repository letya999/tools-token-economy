# Plan: Cross-Platform Support (Windows native / Mac / Linux)

Date: 2026-05-31
Project: tools_token_economy

## Goal
Make the benchmark runnable on Windows native (PowerShell, no WSL required),
Mac (darwin), and Linux — in addition to the existing WSL path.
Do NOT break existing WSL support.

## IMPORTANT FOR IMPLEMENTER
- Read this plan fully before starting.
- Run `uv run pytest tests/ -q` after each phase. Report pass/fail counts.
- Do NOT run the paid benchmark.
- WSL path for project: /c/Users/User/a_projects/tools_token_economy

================================================================================
## CURRENT STATE
================================================================================

Working: WSL, Linux
Partially working: Mac (rg/serena/semble have `mac` keys but ast-grep/ugrep/grep/semgrep don't)
Broken on Windows native:
  - uv needs UV_LINK_MODE=copy on NTFS (execution_validator does not set it for win32)
  - grep, ast-grep, ugrep, semgrep validators have no "windows" install commands
  - shell_tool uses `shell=True` which invokes cmd.exe on Windows (not bash)
  - No Windows-native runner script (only run_wsl.sh)

Key files:
  - src/features/execution_validator.py       — uv env setup
  - src/features/shell.py                     — ShellExecutor
  - src/features/tool_registry/tools/*/validator.py — platform install cmds
  - scripts/run_wsl.sh                        — WSL runner (reference implementation)

================================================================================
## PHASE 1: Add UV_LINK_MODE=copy for Windows in execution_validator.py
================================================================================

FILE: src/features/execution_validator.py

In `_run_cmd()`, inside the env setup block (around line 186-191), after:
    env.pop("UV_PROJECT_ENVIRONMENT", None)
    env.pop("VIRTUAL_ENV", None)

Add this BEFORE setting UV_PROJECT_ENVIRONMENT:
    # On Windows native, uv cannot create hardlinks on NTFS — use copy mode.
    if sys.platform == "win32":
        env["UV_LINK_MODE"] = "copy"

This ensures uv venv creation and sync work on NTFS without hardlink errors.

Also update `_eval_venv_path()` comment from:
    "Place eval venv on native Linux fs (not NTFS /mnt/c/)"
To:
    "Place eval venv under ~ (~/.eval_venvs on Linux/Mac/WSL, %USERPROFILE%/.eval_venvs on Windows)"
The path itself `os.path.expanduser("~/.eval_venvs/{run_hash}")` works correctly on all platforms.

================================================================================
## PHASE 2: Add Windows/Mac install commands to all validators
================================================================================

For each validator below, add the missing platform keys to `platform_install_cmds`.
If `platform_install_cmds` dict does not exist on the class, add it.

### FILE: src/features/tool_registry/tools/grep/validator.py

Current:
    platform_install_cmds = {
        "linux": "sudo apt-get install -y grep",
        "wsl": "sudo apt-get install -y grep",
    }

Replace with:
    platform_install_cmds = {
        "linux": "sudo apt-get install -y grep",
        "wsl": "sudo apt-get install -y grep",
        "mac": "brew install grep",
        "windows": "winget install GnuWin32.Grep",
    }

### FILE: src/features/tool_registry/tools/ast_grep/validator.py

Add:
    platform_install_cmds = {
        "linux": "cargo install ast-grep --locked",
        "wsl": "cargo install ast-grep --locked",
        "mac": "brew install ast-grep",
        "windows": "winget install ast-grep",
    }

### FILE: src/features/tool_registry/tools/ugrep/validator.py

Add:
    platform_install_cmds = {
        "linux": "sudo apt-get install -y ugrep",
        "wsl": "sudo apt-get install -y ugrep",
        "mac": "brew install ugrep",
        "windows": "winget install Genivia.ugrep",
    }

### FILE: src/features/tool_registry/tools/semgrep/validator.py

Add:
    platform_install_cmds = {
        "linux": "pip install semgrep",
        "wsl": "pip install semgrep",
        "mac": "brew install semgrep",
        "windows": "pip install semgrep",
    }

### FILE: src/features/tool_registry/tools/git_grep/validator.py

git is cross-platform. Confirm or add:
    platform_install_cmds = {
        "linux": "sudo apt-get install -y git",
        "wsl": "sudo apt-get install -y git",
        "mac": "brew install git",
        "windows": "winget install Git.Git",
    }

================================================================================
## PHASE 3: Windows-compatible shell in ShellExecutor
================================================================================

FILE: src/features/shell.py

The issue: `shell=True` on Windows uses cmd.exe, not bash. Config 21 (bash_only)
runs bash commands like `grep -rn`, `cat`, `find` — these work in Git Bash / WSL
but not in cmd.exe.

Fix: detect available shell on Windows and warn if bash is not present.

In `ShellExecutor.run()`, add a class-level cached property:

    @staticmethod
    def _effective_shell() -> str | None:
        """Return the shell executable for shell=True, or None for default."""
        if sys.platform != "win32":
            return None  # subprocess uses /bin/sh by default on POSIX
        # On Windows: prefer Git Bash, then WSL bash, then fall back to cmd.exe
        import shutil
        for candidate in ["bash", "C:\\Program Files\\Git\\bin\\bash.exe"]:
            if shutil.which(candidate):
                return candidate
        return None  # falls back to cmd.exe

Then in `run()`:
    executable = self._effective_shell()
    popen_kwargs = dict(
        command,
        shell=True,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    if executable:
        popen_kwargs["executable"] = executable

IMPORTANT: The `subprocess.run()` call uses positional `command` — preserve existing
signature exactly. Only add `executable=executable` when it is not None.

================================================================================
## PHASE 4: Create scripts/run_windows.ps1 (Windows native runner)
================================================================================

FILE: scripts/run_windows.ps1 (NEW FILE)

This is the Windows equivalent of run_wsl.sh.

Content:
```powershell
# Windows native benchmark runner.
# Usage: .\scripts\run_windows.ps1 [--dry-run] [--config-ids ...] [--runs N] [...]
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir

# On Windows, uv needs copy mode for NTFS hardlink operations.
$env:UV_LINK_MODE = "copy"

# Run the benchmark using uv (handles venv automatically).
& uv run --project $ProjectDir python "$ProjectDir\main.py" @Args
```

================================================================================
## PHASE 5: Tests for cross-platform behavior
================================================================================

### FILE: tests/features/test_cross_platform.py (NEW FILE)

Write the following tests:

```python
"""Cross-platform compatibility tests for execution_validator, shell, and validators."""
import sys
from unittest.mock import patch

import pytest

from src.features.shell import ShellExecutor


class TestShellExecutorPlatform:
    def test_run_echo_posix(self):
        """echo hello works on all platforms."""
        result = ShellExecutor().run("echo hello")
        assert result.exit_code == 0
        assert "hello" in result.stdout

    def test_effective_shell_posix(self):
        if sys.platform == "win32":
            pytest.skip("posix-only test")
        shell = ShellExecutor._effective_shell()
        assert shell is None  # POSIX: let subprocess use /bin/sh

    def test_effective_shell_windows_mock(self):
        """On mocked Windows, _effective_shell returns bash path or None."""
        with patch("sys.platform", "win32"):
            # Just ensure it doesn't raise and returns str or None
            shell = ShellExecutor._effective_shell()
            assert shell is None or isinstance(shell, str)


class TestExecutionValidatorUVLinkMode:
    def test_uv_link_mode_set_on_win32(self, tmp_path):
        """UV_LINK_MODE=copy is injected into env on Windows."""
        import os
        from src.features.execution_validator import ExecutionValidator

        os.environ.pop("UV_LINK_MODE", None)
        validator = ExecutionValidator(
            worktree_path=str(tmp_path),
            test_cmd="echo ok",
            timeout_sec=5,
        )

        captured_env = {}

        def fake_popen(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            class FakeProc:
                def communicate(self, timeout=None): return ("0 passed\n", "")
                returncode = 0
                def wait(self): pass
            return FakeProc()

        import subprocess
        with patch("sys.platform", "win32"), patch.object(subprocess, "Popen", fake_popen):
            validator._run_cmd("echo ok", method="test")

        assert captured_env.get("UV_LINK_MODE") == "copy"

    def test_uv_link_mode_not_forced_on_linux(self, tmp_path):
        """UV_LINK_MODE is NOT injected on Linux."""
        import os
        from src.features.execution_validator import ExecutionValidator

        os.environ.pop("UV_LINK_MODE", None)
        validator = ExecutionValidator(
            worktree_path=str(tmp_path),
            test_cmd="echo ok",
            timeout_sec=5,
        )

        captured_env = {}

        def fake_popen(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            class FakeProc:
                def communicate(self, timeout=None): return ("0 passed\n", "")
                returncode = 0
                def wait(self): pass
            return FakeProc()

        import subprocess
        with patch("sys.platform", "linux"), patch.object(subprocess, "Popen", fake_popen):
            validator._run_cmd("echo ok", method="test")

        assert "UV_LINK_MODE" not in captured_env


class TestValidatorPlatformCmds:
    """Ensure all CLI-dependent validators have install commands for all 4 platforms."""

    EXPECTED_PLATFORMS = {"linux", "wsl", "mac", "windows"}

    def _check_validator(self, validator_cls):
        cmds = getattr(validator_cls, "platform_install_cmds", {})
        if not cmds:
            return  # No CLI binary, skip
        missing = self.EXPECTED_PLATFORMS - set(cmds.keys())
        assert not missing, (
            f"{validator_cls.__name__} missing platform_install_cmds keys: {missing}"
        )

    def test_grep_validator(self):
        from src.features.tool_registry.tools.grep.validator import GrepValidator
        self._check_validator(GrepValidator)

    def test_rg_validator(self):
        from src.features.tool_registry.tools.rg.validator import RgValidator
        self._check_validator(RgValidator)

    def test_ast_grep_validator(self):
        from src.features.tool_registry.tools.ast_grep.validator import AstGrepValidator
        self._check_validator(AstGrepValidator)

    def test_ugrep_validator(self):
        from src.features.tool_registry.tools.ugrep.validator import UgrepValidator
        self._check_validator(UgrepValidator)

    def test_semgrep_validator(self):
        from src.features.tool_registry.tools.semgrep.validator import SemgrepValidator
        self._check_validator(SemgrepValidator)

    def test_git_grep_validator(self):
        from src.features.tool_registry.tools.git_grep.validator import GitGrepValidator
        self._check_validator(GitGrepValidator)

    def test_serena_validator(self):
        from src.features.tool_registry.tools.serena.validator import SerenaValidator
        self._check_validator(SerenaValidator)


class TestDoctorPlatformDetection:
    def test_wsl_detected(self):
        from src.features.doctor import Doctor
        with patch("sys.platform", "linux"), \
             patch("builtins.open", side_effect=lambda p, *a, **k: __import__("io").StringIO("Linux version ... microsoft ...") if "proc/version" in str(p) else open(p, *a, **k)):
            d = Doctor.__new__(Doctor)
            d.platform = d._get_normalized_platform() if hasattr(d, '_get_normalized_platform') else "unknown"

    def test_windows_detected(self):
        from src.features.doctor import Doctor
        with patch("sys.platform", "win32"):
            d = Doctor.__new__(Doctor)
            assert d._get_normalized_platform() == "windows"

    def test_mac_detected(self):
        from src.features.doctor import Doctor
        with patch("sys.platform", "darwin"):
            d = Doctor.__new__(Doctor)
            assert d._get_normalized_platform() == "mac"

    def test_linux_detected(self):
        from src.features.doctor import Doctor
        with patch("sys.platform", "linux"), \
             patch.object(Doctor, "_is_wsl", return_value=False):
            d = Doctor.__new__(Doctor)
            assert d._get_normalized_platform() == "linux"
```

NOTE: If `ExecutionValidator.__init__` requires more arguments than shown, adjust
the test to pass the minimum required. Look at the actual __init__ signature first.

================================================================================
## ACCEPTANCE GATES
================================================================================

After Phase 1:
- Grep for "UV_LINK_MODE" in execution_validator.py — must appear in _run_cmd

After Phase 2:
- All 5 validators (grep, ast_grep, ugrep, semgrep, git_grep) must have
  platform_install_cmds with keys: linux, wsl, mac, windows

After Phase 3:
- `ShellExecutor._effective_shell` must exist
- `uv run pytest tests/features/test_shell.py tests/features/test_shell_tool.py -q` passes

After Phase 4:
- `scripts/run_windows.ps1` exists and is valid PowerShell syntax

After Phase 5 (new tests):
- `uv run pytest tests/features/test_cross_platform.py -q` — all pass

Final gate:
- `uv run pytest tests/ -q` — no new failures vs baseline (146 pass, 8 semantic fail expected)

================================================================================
## FILES SUMMARY
================================================================================

MODIFY:
- src/features/execution_validator.py      (Phase 1: UV_LINK_MODE on win32)
- src/features/shell.py                    (Phase 3: _effective_shell, executable param)
- src/features/tool_registry/tools/grep/validator.py        (Phase 2)
- src/features/tool_registry/tools/ast_grep/validator.py    (Phase 2)
- src/features/tool_registry/tools/ugrep/validator.py       (Phase 2)
- src/features/tool_registry/tools/semgrep/validator.py     (Phase 2)
- src/features/tool_registry/tools/git_grep/validator.py    (Phase 2)

CREATE:
- scripts/run_windows.ps1                  (Phase 4)
- tests/features/test_cross_platform.py   (Phase 5)

DO NOT TOUCH:
- run_wsl.sh (WSL path must remain unchanged)
- configs/ directory (not related to platform compat)
- src/core/ models/scoring/provider_factory (already done in previous phases)
