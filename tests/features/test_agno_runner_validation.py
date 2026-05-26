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
        # All calls return empty (no changes in diff or status)
        mock_run.return_value = MagicMock(stdout="", returncode=0)

        success, tests_passed, tests_failed, patch_lines, *_ = runner._validate_run("/tmp/wt", "pytest")

        assert success is False
        assert tests_passed == 0
        assert patch_lines == 0


def test_validate_run_no_test_files(runner):
    """Non-test .py files changed: syntax check passes -> success=True (universal eval)."""
    with patch("subprocess.run") as mock_run:
        # Call order: (1) git diff HEAD, (2) git status --porcelain, (3) py_compile
        mock_run.side_effect = [
            MagicMock(stdout="+ x = 1\n", returncode=0),         # git diff HEAD (patch capture)
            MagicMock(stdout=" M src/main.py\n", returncode=0),   # git status --porcelain
            MagicMock(returncode=0),                               # py_compile syntax check
        ]

        success, tests_passed, tests_failed, patch_lines, *_ = runner._validate_run("/tmp/wt", "pytest")

        # Universal eval: made changes + syntax OK = success (outcome "not_verified", not "failed")
        assert success is True
        assert patch_lines == 1


def test_validate_run_test_passed(runner):
    """If test files changed and tests pass, validation returns success=True with count."""
    with patch("subprocess.run") as mock_run:
        # Call order: (1) git diff HEAD, (2) git status --porcelain, (3) pytest
        mock_run.side_effect = [
            MagicMock(stdout="+ def test(): pass\n", returncode=0),  # git diff HEAD
            MagicMock(stdout="?? tests/test_main.py\n", returncode=0),  # git status --porcelain
            MagicMock(stdout="2 passed in 0.1s", stderr="", returncode=0),  # pytest
        ]

        success, tests_passed, tests_failed, patch_lines, *_ = runner._validate_run("/tmp/wt", "pytest")

        assert success is True
        assert tests_passed == 2
        assert patch_lines == 1


def test_validate_run_test_failed(runner):
    """If test files changed but tests fail, validation returns success=False."""
    with patch("subprocess.run") as mock_run:
        # Call order: (1) git diff HEAD, (2) git status --porcelain, (3) pytest
        mock_run.side_effect = [
            MagicMock(stdout="+ def test(): assert False\n", returncode=0),  # git diff HEAD
            MagicMock(stdout="?? tests/test_main.py\n", returncode=0),  # git status --porcelain
            MagicMock(stdout="1 failed in 0.1s", stderr="", returncode=1),  # pytest
        ]

        success, tests_passed, tests_failed, patch_lines, *_ = runner._validate_run("/tmp/wt", "pytest")

        assert success is False
        assert tests_passed == 0
