"""Cross-platform compatibility tests for execution_validator, shell, and validators."""
import sys
from unittest.mock import patch

import pytest

from src.features.shell import ShellExecutor


class TestShellExecutorPlatform:
    def test_run_simple_command(self):
        """Simple command works on all platforms."""
        result = ShellExecutor().run("echo hello")
        assert result.exit_code == 0
        assert "hello" in result.stdout.lower()

    def test_effective_shell_posix(self):
        if sys.platform == "win32":
            pytest.skip("posix-only test")
        shell = ShellExecutor._effective_shell()
        assert shell is None  # POSIX: let subprocess use /bin/sh

    def test_effective_shell_windows_mock(self):
        """On mocked Windows, _effective_shell returns bash path or None."""
        with patch("sys.platform", "win32"), patch("shutil.which", return_value="bash"):
            shell = ShellExecutor._effective_shell()
            assert shell == "bash"


class TestExecutionValidatorUVLinkMode:
    def test_uv_link_mode_set_on_win32(self, tmp_path):
        """UV_LINK_MODE=copy is injected into env on Windows."""
        import os
        from src.features.execution_validator import ExecutionValidator

        os.environ.pop("UV_LINK_MODE", None)
        validator = ExecutionValidator(
            worktree_path=str(tmp_path),
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
