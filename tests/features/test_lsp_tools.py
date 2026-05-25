import os
import pytest
from src.features.tool_registry.lsp_tools import LspSymbolsTool

@pytest.fixture
def python_repo(tmp_path):
    (tmp_path / "models.py").write_text(
        "class User:\n"
        "    def get_name(self) -> str:\n"
        "        return self.name\n"
        "\n"
        "def create_user(name: str) -> User:\n"
        "    u = User()\n"
        "    u.name = name\n"
        "    print(u.name)\n"
        "    return u\n"
    )
    (tmp_path / "utils.py").write_text(
        "def format_name(name: str) -> str:\n"
        "    return name.strip().title()\n"
    )
    return str(tmp_path)

def test_lsp_symbols_by_file(python_repo):
    tool = LspSymbolsTool(python_repo)
    res = tool.execute(file_path="models.py")
    assert "User" in res.output
    assert "create_user" in res.output
    assert res.tokens > 0

def test_lsp_symbols_by_file_includes_line_numbers(python_repo):
    tool = LspSymbolsTool(python_repo)
    res = tool.execute(file_path="models.py")
    # Should include line number info
    assert "line " in res.output

def test_lsp_symbols_file_not_found(python_repo):
    tool = LspSymbolsTool(python_repo)
    res = tool.execute(file_path="nonexistent.py")
    assert "File not found" in res.output

def test_lsp_symbols_by_symbol_name(python_repo):
    tool = LspSymbolsTool(python_repo)
    res = tool.execute(symbol="create_user")
    assert "create_user" in res.output
    assert "models.py" in res.output

def test_lsp_symbols_by_symbol_cross_file(python_repo):
    tool = LspSymbolsTool(python_repo)
    res = tool.execute(symbol="format_name")
    assert "utils.py" in res.output

def test_lsp_symbols_no_args_returns_error(python_repo):
    tool = LspSymbolsTool(python_repo)
    res = tool.execute()
    assert "Provide" in res.output

def test_lsp_symbols_nonexistent_symbol(python_repo):
    tool = LspSymbolsTool(python_repo)
    res = tool.execute(symbol="totally_nonexistent_xyz")
    assert "not found" in res.output.lower()

def test_lsp_symbols_no_stdlib_leakage(python_repo):
    tool = LspSymbolsTool(python_repo)
    # 'print' is a builtin, Jedi might find it in stdlib if not filtered.
    res = tool.execute(symbol="print")
    # Should either be not found (as it's a builtin, not a defined project symbol)
    # or if found, it MUST NOT point to a path outside the project (like /usr/lib/python...)
    output = res.output.lower()
    if "symbol 'print' not found" not in output:
        # If it found something, verify it doesn't contain common stdlib/venv indicators
        assert "site-packages" not in output
        assert "lib/python" not in output
        assert "python3" not in output
