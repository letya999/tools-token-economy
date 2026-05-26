from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.structural_tools import RepoMapTool


class RepoMapValidator(BaseToolValidator):
    tool_name = "repo_map"
    def _get_tool_instance(self, tmp_dir): return RepoMapTool(tmp_dir)
