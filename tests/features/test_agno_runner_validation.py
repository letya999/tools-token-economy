import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.core.models import AgentConfig
from src.features.agent_integration.agno_runner import AgnoRunner


@pytest.fixture
def runner():
    config = AgentConfig(id="test", name="Test", archetype="test", tools=[])
    return AgnoRunner(config, tools=[])


def test_max_iterations_caps_tool_call_limit():
    """max_iterations from BenchmarkMeta caps agent's tool_call_limit."""
    config = AgentConfig(id="test", name="Test", archetype="test", tools=[], max_steps=50)
    runner = AgnoRunner(config, tools=[], max_iterations=10)

    with patch("src.features.agent_integration.agno_runner.Agent") as mock_agent_cls, \
         patch("src.features.agent_integration.agno_runner.build_agent_model"):
        mock_agent_cls.return_value = MagicMock()
        runner._build_agent("gpt-4o-mini", [], "/tmp/wt")
        _, kwargs = mock_agent_cls.call_args
        assert kwargs["tool_call_limit"] == 10  # min(50, 10) = 10


def test_max_iterations_does_not_increase_config_limit():
    """max_iterations > config.max_steps: config limit wins."""
    config = AgentConfig(id="test", name="Test", archetype="test", tools=[], max_steps=5)
    runner = AgnoRunner(config, tools=[], max_iterations=20)

    with patch("src.features.agent_integration.agno_runner.Agent") as mock_agent_cls, \
         patch("src.features.agent_integration.agno_runner.build_agent_model"):
        mock_agent_cls.return_value = MagicMock()
        runner._build_agent("gpt-4o-mini", [], "/tmp/wt")
        _, kwargs = mock_agent_cls.call_args
        assert kwargs["tool_call_limit"] == 5  # min(5, 20) = 5


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


def _mock_popen(stdout: str, stderr: str, returncode: int):
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = (stdout, stderr)
    mock_proc.returncode = returncode
    return mock_proc


def test_validate_run_test_passed(runner):
    """If test files changed and tests pass, validation returns success=True with count."""
    with patch("subprocess.run") as mock_run, \
         patch("subprocess.Popen") as mock_popen:
        # subprocess.run: (1) git diff HEAD, (2) git status --porcelain
        mock_run.side_effect = [
            MagicMock(stdout="+ def test(): pass\n", returncode=0),
            MagicMock(stdout="?? tests/test_main.py\n", returncode=0),
        ]
        # subprocess.Popen: pytest (now uses Popen for timeout handling)
        mock_popen.return_value = _mock_popen("2 passed in 0.1s", "", 0)

        success, tests_passed, tests_failed, patch_lines, *_ = runner._validate_run("/tmp/wt", "pytest")

        assert success is True
        assert tests_passed == 2
        assert patch_lines == 1


def test_validate_run_test_failed(runner):
    """If test files changed but tests fail, validation returns success=False."""
    with patch("subprocess.run") as mock_run, \
         patch("subprocess.Popen") as mock_popen:
        mock_run.side_effect = [
            MagicMock(stdout="+ def test(): assert False\n", returncode=0),
            MagicMock(stdout="?? tests/test_main.py\n", returncode=0),
        ]
        mock_popen.return_value = _mock_popen("1 failed in 0.1s", "", 1)

        success, tests_passed, tests_failed, patch_lines, *_ = runner._validate_run("/tmp/wt", "pytest")

        assert success is False
        assert tests_passed == 0


def test_net_spt_computation(runner):
    """Verify schema_overhead_tokens and net_spt are correctly calculated."""
    with patch.object(runner, "_extract_metrics_from_response") as mock_extract, \
         patch.object(runner, "_validate_run") as mock_validate, \
         patch("src.features.agent_integration.agno_runner.Agent") as mock_agent_cls, \
         patch("src.features.agent_integration.agno_runner.build_agent_model"):
        
        mock_extract.return_value = {
            "input_tokens": 1000,
            "output_tokens": 200,
            "tool_tokens": 300,
            "model_calls": 5,
            "tool_calls": 2,
            "files_read": 1,
            "tool_schema_bytes": 400,  # 400/4 = 100 tokens overhead per call
        }
        mock_validate.return_value = (True, 1, 0, 10, "passed", True, "", "")
        
        mock_agent = MagicMock()
        mock_agent.run.return_value = MagicMock()
        mock_agent_cls.return_value = mock_agent
        
        metrics = runner.run("task")
        
        # total_tokens = 1000 + 200 + 300 = 1500
        # schema_overhead = int((400 / 4) * 5) = 500
        assert metrics.schema_overhead_tokens == 500
        
        # reasoning_tokens = max(1500 - 500, 1) = 1000
        # net_spt = 1000.0 / 1000 = 1.0 (since success is True)
        assert metrics.net_spt == 1.0
