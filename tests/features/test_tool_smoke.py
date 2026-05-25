import os
import shutil
import subprocess
import tempfile
import pytest
from src.features.tool_registry.grep_tools import AstGrepTool, GrepTool, GitGrepTool, RgTool, UgrepTool, SemgrepTool
from src.features.tool_registry.structural_tools import TreeSitterTool, RepoMapTool
from src.features.tool_registry.lsp_tools import LspSymbolsTool
from src.features.tool_registry.basic_tools import FileReadTool, FileWriteTool, GlobTool, PatchApplierTool

def _on_rm_error(func, path, exc_info):
    """Error handler for shutil.rmtree to handle read-only files (common in .git)."""
    import stat
    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR)
        func(path)
    else:
        raise

@pytest.fixture
def smoke_repo():
    """Create a temporary git repo with some python files for tool testing."""
    tmp_dir = tempfile.mkdtemp()
    
    # Create test files
    with open(os.path.join(tmp_dir, "main.py"), "w") as f:
        f.write("def main_func():\n    print('hello world')\n")
    
    with open(os.path.join(tmp_dir, "utils.py"), "w") as f:
        f.write("def util_func():\n    return 42\n")
        
    with open(os.path.join(tmp_dir, "data.txt"), "w") as f:
        f.write("some non-python data\n")

    # Init git
    subprocess.run(["git", "init", "-q"], cwd=tmp_dir)
    subprocess.run(["git", "add", "."], cwd=tmp_dir)
    subprocess.run(["git", "config", "user.email", "smoke@test.com"], cwd=tmp_dir)
    subprocess.run(["git", "config", "user.name", "Smoke Test"], cwd=tmp_dir)
    subprocess.run(["git", "commit", "-m", "init", "-q"], cwd=tmp_dir)
    
    yield tmp_dir
    shutil.rmtree(tmp_dir, onerror=_on_rm_error)

def test_grep_smoke(smoke_repo):
    if not shutil.which("grep"):
        pytest.skip("grep not installed")
    tool = GrepTool(smoke_repo)
    res = tool.execute("main_func")
    assert "main.py" in res.output
    assert "main_func" in res.output

def test_git_grep_smoke(smoke_repo):
    tool = GitGrepTool(smoke_repo)
    res = tool.execute("util_func")
    assert "utils.py" in res.output
    assert "util_func" in res.output

def test_rg_smoke(smoke_repo):
    if not shutil.which("rg"):
        pytest.skip("ripgrep not installed")
    tool = RgTool(smoke_repo)
    res = tool.execute("hello world")
    assert "main.py" in res.output

def test_ast_grep_smoke(smoke_repo):
    if not shutil.which("ast-grep"):
        pytest.skip("ast-grep not installed")
    tool = AstGrepTool(smoke_repo)
    # print($A) matches call expressions - function def metavars invalid in Python AST
    res = tool.execute("print($A)")
    assert "main.py" in res.output
    assert "print" in res.output
    assert "data.txt" not in res.output  # --lang python filters non-.py files


def test_semgrep_smoke(smoke_repo):
    if not shutil.which("semgrep"):
        pytest.skip("semgrep not installed")
    tool = SemgrepTool(smoke_repo)
    res = tool.execute("def $F(...): ...")
    assert "main.py" in res.output
    assert "data.txt" not in res.output

def test_tree_sitter_smoke(smoke_repo):
    tool = TreeSitterTool(smoke_repo)
    res = tool.execute("main.py")
    assert "main_func" in res.output

def test_lsp_symbols_smoke(smoke_repo):
    tool = LspSymbolsTool(smoke_repo)
    res = tool.execute(symbol="main_func")
    assert "main.py" in res.output
    assert "main_func" in res.output

def test_basic_file_tools_smoke(smoke_repo):
    read = FileReadTool(smoke_repo)
    write = FileWriteTool(smoke_repo)
    
    # Write
    write.execute("new.py", "def new(): pass")
    assert os.path.exists(os.path.join(smoke_repo, "new.py"))
    
    # Read
    res = read.execute("new.py")
    assert "def new(): pass" in res.output

def test_patch_smoke(smoke_repo):
    tool = PatchApplierTool(smoke_repo)
    patch = """--- main.py
+++ main.py
@@ -1,2 +1,2 @@
 def main_func():
-    print('hello world')
+    print('hello universe')
"""
    res = tool.execute(patch)
    assert "successfully" in res.output.lower()
    with open(os.path.join(smoke_repo, "main.py")) as f:
        assert "universe" in f.read()
