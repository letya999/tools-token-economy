from src.features.tool_registry.base import BaseToolValidator, ValidationResult 
from src.features.tool_registry.semantic_tools import SimpleRagTool


class SimpleRagValidator(BaseToolValidator):
    tool_name = "simple_rag"
    cli_binary = None

    def _get_tool_instance(self, tmp_dir): return SimpleRagTool(tmp_dir)        

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        try:
            tool = SimpleRagTool(tmp_dir)
            # Just check it instantiates without error
            return ValidationResult(passed=True, detail="SimpleRagTool instantiated")
        except Exception as e:
            return ValidationResult(passed=False, detail=str(e))

    def prepare(self, repo_path: str) -> ValidationResult:
        """Expensive: ingest repository into RAG index."""
        try:
            tool = SimpleRagTool(repo_path)
            stats = tool.ingest()
            return ValidationResult(
                passed=stats.get("status") != "error",
                detail=f"RAG ingested: files={stats.get('files','?')}, chunks={stats.get('chunks','?')}"
            )
        except Exception as e:
            return ValidationResult(passed=False, detail=f"RAG ingestion failed: {e}")
