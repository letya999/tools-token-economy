from src.features.tool_registry.base import BaseToolValidator, ValidationResult
from src.features.tool_registry.semantic_tools import SimpleRagTool, _dense_model, _sparse_model


class SimpleRagValidator(BaseToolValidator):
    tool_name = "simple_rag"
    cli_binary = None

    def _get_tool_instance(self, tmp_dir): return SimpleRagTool(tmp_dir)

    def smoke_test(self, tmp_dir: str) -> ValidationResult:
        try:
            SimpleRagTool(tmp_dir)
            # Pre-warm fastembed models so they are cached before the first real run.
            # First call downloads ~50 MB; subsequent calls are instant (HF cache).
            _dense_model()
            _sparse_model()
            return ValidationResult(passed=True, detail="SimpleRagTool instantiated; fastembed models ready")
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
