from unittest.mock import MagicMock, patch

import pytest

from src.features.mcp_client import McpToolClient


def test_mcp_client_constructs_server_params():
    # Use a dummy server to avoid real process spawning issues in construct-only test
    with patch("src.features.mcp_client.threading.Thread"):
        client = McpToolClient(
            server_command="serena",
            server_args=["start-mcp-server", "--project", "/tmp/repo"],
            cwd="/tmp/repo",
        )
    assert client.server_params.command == "serena"
    assert "start-mcp-server" in client.server_params.args
    assert "--project" in client.server_params.args


def test_mcp_client_call_tool_returns_result():
    """Mock the queue communication to test call_tool sync facade."""
    with patch("src.features.mcp_client.threading.Thread"):
        client = McpToolClient(server_command="serena", server_args=[])

        # Simulate response in queue
        client._response_queue.put("mocked result")

        result = client.call_tool("any_tool", {})
        assert result == "mocked result"
        assert client._request_queue.get()[0] == "call_tool"


def test_mcp_client_list_tools_returns_list():
    with patch("src.features.mcp_client.threading.Thread"):
        client = McpToolClient(server_command="serena", server_args=[])

        client._response_queue.put(["tool1", "tool2"])

        result = client.list_tools()
        assert result == ["tool1", "tool2"]
        assert client._request_queue.get()[0] == "list_tools"


def test_mcp_client_call_tool_raises_on_exception():
    with patch("src.features.mcp_client.threading.Thread"):
        client = McpToolClient(server_command="serena", server_args=[])

        client._response_queue.put(RuntimeError("error"))

        with pytest.raises(RuntimeError, match="error"):
            client.call_tool("any_tool", {})


def test_mcp_client_list_tools_returns_empty_on_exception():
    with patch("src.features.mcp_client.threading.Thread"):
        client = McpToolClient(server_command="serena", server_args=[])

        client._response_queue.put(RuntimeError("error"))

        result = client.list_tools()
        assert result == []


@pytest.mark.anyio
async def test_mcp_client_format_result_handles_text():
    # We patch Thread to not start real loop
    with patch("src.features.mcp_client.threading.Thread"):
        client = McpToolClient(server_command="serena", server_args=[])

        mock_block = MagicMock()
        mock_block.text = "hello"
        mock_result = MagicMock()
        mock_result.content = [mock_block]

        formatted = client._format_result(mock_result)
        assert formatted == "hello"
        client.close()


@pytest.mark.anyio
async def test_mcp_client_format_result_handles_non_text():
    with patch("src.features.mcp_client.threading.Thread"):
        client = McpToolClient(server_command="serena", server_args=[])

        class _Block:
            def __init__(self):
                self.foo = "bar"
            def __str__(self):
                return "fallback"

        mock_result = MagicMock()
        mock_result.content = [_Block()]

        formatted = client._format_result(mock_result)
        # It will use json.dumps or str() fallback
        assert "bar" in formatted or "fallback" in formatted
        client.close()
