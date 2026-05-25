import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.core.models import AgentConfig
from src.features.agent_integration.agno_runner import AgnoRunner


@pytest.fixture
def runner():
    config = AgentConfig(id="test", name="Test", archetype="test", tools=[])
    return AgnoRunner(config, tools=[])


def test_validate_run_no_changes(runner):
    """If git status shows no changed files, validation returns success=False immediately."""
    with patch("subprocess.run") as mock_run:
        # git status --porcelain returns empty output
        mock_run.return_value = MagicMock(stdout="", returncode=0)

        success, tests_passed, patch_lines = runner._validate_run("/tmp/wt", "pytest")

        assert success is False
        assert tests_passed == 0
        assert patch_lines == 0


def test_validate_run_no_test_files(runner):
    """If only non-test files changed, validation returns success=False."""
    with patch("subprocess.run") as mock_run:
        # git status --porcelain: modified non-test file
        # git diff HEAD: one added line
        mock_run.side_effect = [
            MagicMock(stdout=" M src/main.py\n", returncode=0),
            MagicMock(stdout="+ x = 1\n", returncode=0),
        ]

        success, tests_passed, patch_lines = runner._validate_run("/tmp/wt", "pytest")

        assert success is False
        assert patch_lines == 1


def test_validate_run_test_passed(runner):
    """If test files changed and tests pass, validation returns success=True with count."""
    with patch("subprocess.run") as mock_run:
        # git status --porcelain: new untracked test file
        # git diff HEAD: one added line
        # pytest via EvalEngine/ShellExecutor: 2 passed
        mock_run.side_effect = [
            MagicMock(stdout="?? tests/test_main.py\n", returncode=0),
            MagicMock(stdout="+ def test(): pass\n", returncode=0),
            MagicMock(stdout="2 passed in 0.1s", stderr="", returncode=0),
        ]

        success, tests_passed, patch_lines = runner._validate_run("/tmp/wt", "pytest")

        assert success is True
        assert tests_passed == 2
        assert patch_lines == 1


def test_validate_run_test_failed(runner):
    """If test files changed but tests fail, validation returns success=False."""
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(stdout="?? tests/test_main.py\n", returncode=0),
            MagicMock(stdout="+ def test(): assert False\n", returncode=0),
            MagicMock(stdout="1 failed in 0.1s", stderr="", returncode=1),
        ]

        success, tests_passed, patch_lines = runner._validate_run("/tmp/wt", "pytest")

        assert success is False
        assert tests_passed == 0
