import pytest
from unittest.mock import MagicMock, patch
from src.features.agent_integration.opencode_runner import OpenCodeRunner
from src.core.models import AgentConfig
from src.core.tools import Tool, ToolResult

@pytest.fixture
def mock_tool():
    tool = MagicMock(spec=Tool)
    tool.name = "test_tool"
    tool.description = "A test tool"
    tool.execute.return_value = ToolResult(output="Tool result", token_count=10)
    return tool

@pytest.fixture
def agent_config():
    return AgentConfig(
        id="test_agent",
        name="Test Agent",
        archetype="test",
        tools=["test_tool"],
        max_steps=2
    )

def test_opencode_runner_loop_basic(agent_config, mock_tool):
    # Mocking Gemini API response
    with patch("google.generativeai.GenerativeModel") as mock_model_class:
        mock_model = mock_model_class.return_value
        
        # Simulate two turns: 1. Tool call, 2. Final answer
        mock_response_1 = MagicMock()
        mock_response_1.text = 'I need to call test_tool. {"tool": "test_tool", "args": {}}'
        
        mock_response_2 = MagicMock()
        mock_response_2.text = "Task complete. TASK_COMPLETE"
        
        mock_model.generate_content.side_effect = [mock_response_1, mock_response_2]
        
        runner = OpenCodeRunner(config=agent_config, tools=[mock_tool])
        result = runner.run(task_description="Do something")
        
        assert result is not None
        assert runner.step_count <= 2
        # Verify tokens were tracked (at least placeholders for now)
        assert result.input_tokens > 0
        assert result.output_tokens > 0
