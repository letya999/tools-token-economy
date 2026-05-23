import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from mcp import StdioServerParameters
from src.features.mcp_client import McpToolClient


def test_mcp_client_constructs_server_params():
    client = McpToolClient(
        server_command="serena",
        server_args=["start-mcp-server", "--project", "/tmp/repo"],
        cwd="/tmp/repo",
    )
    assert client.server_params.command == "serena"
    assert "start-mcp-server" in client.server_params.args
    assert "--project" in client.server_params.args


def test_mcp_client_call_tool_returns_error_string_on_exception():
    """call_tool wraps exceptions and returns an error string, never raises."""
    client = McpToolClient(server_command="nonexistent_xyz", server_args=[])
    # Patch asyncio as seen by mcp_client module so the try/except catches it
    with patch("src.features.mcp_client.asyncio") as mock_asyncio:
        mock_asyncio.run.side_effect = RuntimeError("server not found")
        result = client.call_tool("find_symbol", {"query": "User"})
    assert "Error" in result
    assert isinstance(result, str)


def test_mcp_client_list_tools_returns_empty_on_exception():
    """list_tools returns [] gracefully on any error."""
    client = McpToolClient(server_command="nonexistent_xyz", server_args=[])
    with patch("src.features.mcp_client.asyncio") as mock_asyncio:
        mock_asyncio.run.side_effect = OSError("binary not found")
        result = client.list_tools()
    assert result == []


@pytest.mark.anyio
async def test_mcp_client_async_call_assembles_text_content():
    """_async_call_tool joins multiple text content blocks with newlines."""
    mock_block1 = MagicMock()
    mock_block1.text = "symbol: User at line 5"
    mock_block2 = MagicMock()
    mock_block2.text = "symbol: AdminUser at line 42"

    mock_result = MagicMock()
    mock_result.content = [mock_block1, mock_block2]

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)
    mock_session.initialize = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_streams = (AsyncMock(), AsyncMock())

    client = McpToolClient(server_command="serena", server_args=[])

    with patch("src.features.mcp_client.stdio_client") as mock_stdio, \
         patch("src.features.mcp_client.ClientSession") as mock_session_cls:
        mock_stdio.return_value.__aenter__ = AsyncMock(return_value=mock_streams)
        mock_stdio.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_session

        result = await client._async_call_tool("find_symbol", {"query": "User"})

    assert "User at line 5" in result
    assert "AdminUser at line 42" in result


@pytest.mark.anyio
async def test_mcp_client_async_call_fallback_for_non_text_blocks():
    """Content blocks without .text attribute use str() fallback."""
    class _Block:
        def __str__(self):
            return "raw block content"

    mock_block = _Block()

    mock_result = MagicMock()
    mock_result.content = [mock_block]

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)
    mock_session.initialize = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_streams = (AsyncMock(), AsyncMock())
    client = McpToolClient(server_command="serena", server_args=[])

    with patch("src.features.mcp_client.stdio_client") as mock_stdio, \
         patch("src.features.mcp_client.ClientSession") as mock_session_cls:
        mock_stdio.return_value.__aenter__ = AsyncMock(return_value=mock_streams)
        mock_stdio.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_session

        result = await client._async_call_tool("any_tool", {})

    assert "raw block content" in result


@pytest.mark.anyio
async def test_mcp_client_async_list_tools():
    mock_tool1 = MagicMock()
    mock_tool1.name = "find_symbol"
    mock_tool2 = MagicMock()
    mock_tool2.name = "get_symbols_overview"

    mock_tools_result = MagicMock()
    mock_tools_result.tools = [mock_tool1, mock_tool2]

    mock_session = AsyncMock()
    mock_session.list_tools = AsyncMock(return_value=mock_tools_result)
    mock_session.initialize = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_streams = (AsyncMock(), AsyncMock())
    client = McpToolClient(server_command="serena", server_args=[])

    with patch("src.features.mcp_client.stdio_client") as mock_stdio, \
         patch("src.features.mcp_client.ClientSession") as mock_session_cls:
        mock_stdio.return_value.__aenter__ = AsyncMock(return_value=mock_streams)
        mock_stdio.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session_cls.return_value = mock_session

        result = await client._async_list_tools()

    assert result == ["find_symbol", "get_symbols_overview"]
