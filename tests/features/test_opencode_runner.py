import json
from unittest.mock import MagicMock, patch

import pytest

from src.core.models import AgentConfig
from src.core.tools import Tool
from src.features.agent_integration.opencode_runner import OpenCodeRunner


@pytest.fixture(autouse=True)
def dummy_env():
    """Ensure API keys are present for tests."""
    with patch.dict("os.environ", {
        "GOOGLE_GENAI_API_KEY": "fake-key",
        "OPENAI_API_KEY": "fake-key",
        "ANTHROPIC_API_KEY": "fake-key",
        "OPENROUTER_API_KEY": "fake-key"
    }):
        yield

@pytest.fixture
def mock_tool():
    tool = MagicMock(spec=Tool)
    tool.name = "read"
    return tool

@pytest.fixture
def agent_config():
    return AgentConfig(
        id="test_agent",
        name="Test Agent",
        archetype="test",
        tools=["read"],
        max_steps=2
    )

def test_opencode_runner_mock_mode(agent_config, mock_tool):
    """Verify mock mode returns simulated metrics."""
    runner = OpenCodeRunner(config=agent_config, tools=[mock_tool], mock=True)
    result = runner.run(task_description="Do something")

    assert result.success is True
    assert result.eval_score == 1.0
    assert result.model_calls == 1

def test_opencode_runner_real_mode_mocked(agent_config, mock_tool):
    """Verify real mode correctly parses opencode JSONL events."""
    runner = OpenCodeRunner(config=agent_config, tools=[mock_tool], mock=False)

    # opencode emits step_finish (not 'usage') and tool_use (not 'tool_call')
    jsonl_output = "\n".join([
        json.dumps({"type": "step_finish", "usage": {"inputTokens": 100, "outputTokens": 50}}),
        json.dumps({"type": "tool_use", "part": {"name": "read", "output": "file content"}}),
        json.dumps({"type": "tool_use", "part": {"name": "patch", "output": "line1\nline2\nline3"}}),
        "Finished task successfully",
    ])

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=jsonl_output,
            stderr="",
        )

        result = runner.run(task_description="Do something")

        assert result.success is True
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.tool_calls == 2
        assert result.files_read == 1    # read tool
        assert result.files_changed == 1  # patch tool
        assert result.patch_lines == 2   # 2 newlines in "line1\nline2\nline3"
        assert result.model_calls == 1

def test_opencode_runner_model_flag_format(agent_config, mock_tool):
    """Verify model name is correctly converted to provider/model format."""
    runner = OpenCodeRunner(config=agent_config, tools=[mock_tool], mock=False)
    assert runner._model_flag() == "google/gemini-2.5-flash"

    agent_config_claude = agent_config.model_copy(update={"model": "claude-sonnet-4-6"})
    runner2 = OpenCodeRunner(config=agent_config_claude, tools=[mock_tool], mock=False)
    assert runner2._model_flag() == "anthropic/claude-sonnet-4-6"

def test_opencode_runner_error_events(agent_config, mock_tool):
    """Error events increment error counter; failed exit code means not success."""
    runner = OpenCodeRunner(config=agent_config, tools=[mock_tool], mock=False)

    jsonl_output = "\n".join([
        json.dumps({"type": "error", "message": "rate limit hit"}),
        json.dumps({"type": "error", "message": "tool failed"}),
    ])

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout=jsonl_output, stderr="")
        result = runner.run(task_description="fail")

    assert result.success is False
    assert result.errors == 2

def test_opencode_runner_fallback_token_estimation(agent_config, mock_tool):
    """If no structured usage events, tokens are estimated from raw text."""
    runner = OpenCodeRunner(config=agent_config, tools=[mock_tool], mock=False)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="plain text output without jsonl events",
            stderr="",
        )
        result = runner.run(task_description="simple task")

    # Fallback: input from task, output from stdout
    assert result.input_tokens > 0
    assert result.output_tokens > 0
