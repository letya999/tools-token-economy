"""
ToolRegistry: central management for all benchmark tools and their validators.
"""
import logging
from typing import Any, Type

from src.features.tool_registry.base import BaseToolValidator
# Import all tools
from src.features.tool_registry.basic_tools import (
    FileReadTool, FileWriteTool, GlobTool, PatchApplierTool, ReadAllTool,
    InsertAfterTool, InsertAfterLineTool, AppendToFileTool, StrReplaceEditTool,
)
from src.features.tool_registry.grep_tools import (
    AstGrepTool, GitGrepTool, GrepTool, RgTool, SemgrepTool, UgrepTool
)
from src.features.tool_registry.lsp_tools import LspSymbolsTool
from src.features.tool_registry.semantic_tools import SimpleRagTool
from src.features.tool_registry.shell_tool import ShellTool
from src.features.tool_registry.structural_tools import RepoMapTool, TreeSitterTool

# Import validators
from src.features.tool_registry.tools.read.validator import ReadValidator
from src.features.tool_registry.tools.read_all.validator import ReadAllValidator
from src.features.tool_registry.tools.write.validator import WriteValidator
from src.features.tool_registry.tools.patch.validator import PatchValidator
from src.features.tool_registry.tools.insert_after.validator import InsertAfterValidator
from src.features.tool_registry.tools.glob.validator import GlobValidator
from src.features.tool_registry.tools.rg.validator import RgValidator
from src.features.tool_registry.tools.grep.validator import GrepValidator
from src.features.tool_registry.tools.git_grep.validator import GitGrepValidator
from src.features.tool_registry.tools.ugrep.validator import UgrepValidator
from src.features.tool_registry.tools.ast_grep.validator import AstGrepValidator
from src.features.tool_registry.tools.semgrep.validator import SemgrepValidator
from src.features.tool_registry.tools.tree_sitter.validator import TreeSitterValidator
from src.features.tool_registry.tools.repo_map.validator import RepoMapValidator
from src.features.tool_registry.tools.simple_rag.validator import SimpleRagValidator
from src.features.tool_registry.tools.lsp_symbols.validator import LspSymbolsValidator
from src.features.tool_registry.tools.serena.validator import SerenaValidator
from src.features.tool_registry.tools.semble.validator import SembleValidator
from src.features.tool_registry.tools.shell.validator import ShellValidator

_log = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, worktree_path: str):
        self.worktree_path = worktree_path
        
        # Tool name -> Class
        self._tool_classes = {
            "read": FileReadTool,
            "read_all": ReadAllTool,
            "write": FileWriteTool,
            "edit": StrReplaceEditTool,
            "patch": PatchApplierTool,
            "insert_after": InsertAfterTool,
            "insert": InsertAfterLineTool,
            "append": AppendToFileTool,
            "glob": GlobTool,
            "rg": RgTool,
            "grep": GrepTool,
            "git_grep": GitGrepTool,
            "ugrep": UgrepTool,
            "ast_grep": AstGrepTool,
            "semgrep": SemgrepTool,
            "tree_sitter": TreeSitterTool,
            "repo_map": RepoMapTool,
            "simple_rag": SimpleRagTool,
            "lsp_symbols": LspSymbolsTool,
            "shell": ShellTool,
        }

        # Tool name -> Validator Class
        self._validators: dict[str, Type[BaseToolValidator]] = {
            "read": ReadValidator,
            "read_all": ReadAllValidator,
            "write": WriteValidator,
            "patch": PatchValidator,
            "insert_after": InsertAfterValidator,
            "glob": GlobValidator,
            "rg": RgValidator,
            "grep": GrepValidator,
            "git_grep": GitGrepValidator,
            "ugrep": UgrepValidator,
            "ast_grep": AstGrepValidator,
            "semgrep": SemgrepValidator,
            "tree_sitter": TreeSitterValidator,
            "repo_map": RepoMapValidator,
            "simple_rag": SimpleRagValidator,
            "lsp_symbols": LspSymbolsValidator,
            "serena": SerenaValidator,
            "semble": SembleValidator,
            "shell": ShellValidator,
        }

    def get_tool(self, name: str) -> Any:
        cls = self._tool_classes.get(name)
        if not cls:
            return None
        return cls(self.worktree_path)

    def get_validator(self, name: str) -> BaseToolValidator | None:
        cls = self._validators.get(name)
        if not cls:
            # Return generic validator if no specific one exists
            v = BaseToolValidator()
            v.tool_name = name
            return v
        return cls()

    def list_tools(self) -> list[str]:
        return list(self._tool_classes.keys())
