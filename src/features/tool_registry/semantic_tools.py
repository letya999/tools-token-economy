import os

from src.core.tools import BaseTool, ToolResult

# Lazy module-level singletons — avoid paying import cost unless the tool is used.
_QDRANT_CLIENT_CLS = None
_QDRANT_MODELS = None
_DENSE_MODEL = None
_SPARSE_MODEL = None


def _qdrant_client():
    global _QDRANT_CLIENT_CLS
    if _QDRANT_CLIENT_CLS is None:
        from qdrant_client import QdrantClient
        _QDRANT_CLIENT_CLS = QdrantClient
    return _QDRANT_CLIENT_CLS


def _qdrant_models():
    global _QDRANT_MODELS
    if _QDRANT_MODELS is None:
        from qdrant_client import models
        _QDRANT_MODELS = models
    return _QDRANT_MODELS


def _dense_model():
    global _DENSE_MODEL
    if _DENSE_MODEL is None:
        from fastembed import TextEmbedding
        _DENSE_MODEL = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    return _DENSE_MODEL


def _sparse_model():
    """BM25 tokenizer from Qdrant — no ML download, computes TF-IDF on the fly."""
    global _SPARSE_MODEL
    if _SPARSE_MODEL is None:
        from fastembed import SparseTextEmbedding
        _SPARSE_MODEL = SparseTextEmbedding(model_name="Qdrant/bm25")
    return _SPARSE_MODEL


class SimpleRagTool(BaseTool):
    """
    Hybrid RAG: Qdrant in-memory with named dense (384-dim cosine) + sparse (BM25) vectors.
    At query time, both retrievers run independently and results are fused via RRF.

    Call ingest() from the orchestrator BEFORE starting AgnoRunner so that index-building
    time is excluded from the agent's measured duration_sec.
    """

    _COLLECTION = "rag"
    _DENSE_DIM = 384

    def __init__(self, worktree_path: str):
        super().__init__(
            "simple_rag",
            "Hybrid semantic + BM25 code search using Qdrant + fastembed (RRF fusion)",
        )
        self.worktree_path = worktree_path
        self._client = None
        self._file_count = 0
        self._chunk_count = 0

    @property
    def _ingested(self) -> bool:
        return self._client is not None

    def ingest(self) -> dict:
        """Build dense + sparse index over worktree Python files.

        Idempotent — safe to call multiple times; subsequent calls return cached stats.
        Intended to be called from BenchmarkOrchestrator before AgnoRunner.run() so
        ingestion time is not charged to the agent's duration_sec metric.
        """
        if self._ingested:
            return {"status": "cached", "files": self._file_count, "chunks": self._chunk_count}
        self._init_rag()
        return {"status": "done", "files": self._file_count, "chunks": self._chunk_count}

    def _init_rag(self) -> None:
        if self._ingested:
            return

        qm = _qdrant_models()
        QdrantClient = _qdrant_client()

        self._client = QdrantClient(":memory:")
        self._client.create_collection(
            collection_name=self._COLLECTION,
            vectors_config={
                "dense": qm.VectorParams(size=self._DENSE_DIM, distance=qm.Distance.COSINE),
            },
            sparse_vectors_config={
                "sparse": qm.SparseVectorParams(index=qm.SparseIndexParams()),
            },
        )
        self._build_index()

    def _build_index(self) -> None:
        qm = _qdrant_models()
        dense = _dense_model()
        sparse = _sparse_model()

        points = []
        point_id = 1
        _SKIP_DIRS = {
            ".git", "node_modules", "__pycache__",
            ".venv", "venv", ".venv-wsl", ".venv-win",
            "site-packages", "dist-packages",
            "dist", "build", ".tox", ".mypy_cache", ".ruff_cache",
            ".pytest_cache",
        }

        def _should_skip(d: str) -> bool:
            return d in _SKIP_DIRS or d.endswith(".egg-info") or d.startswith(".venv")

        for root, dirs, files in os.walk(self.worktree_path):
            dirs[:] = [d for d in dirs if not _should_skip(d)]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, self.worktree_path)
                try:
                    with open(full, encoding="utf-8") as fh:
                        lines = fh.readlines()
                except Exception:
                    continue

                self._file_count += 1
                chunk_size, overlap = 50, 10

                for i in range(0, len(lines), chunk_size - overlap):
                    chunk = lines[i: i + chunk_size]
                    if not chunk:
                        break
                    text = "".join(chunk)

                    dense_vec = list(dense.embed([text]))[0].tolist()
                    sparse_emb = list(sparse.embed([text]))[0]
                    sparse_vec = qm.SparseVector(
                        indices=sparse_emb.indices.tolist(),
                        values=sparse_emb.values.tolist(),
                    )

                    points.append(
                        qm.PointStruct(
                            id=point_id,
                            vector={"dense": dense_vec, "sparse": sparse_vec},
                            payload={
                                "file": rel,
                                "start_line": i + 1,
                                "end_line": i + len(chunk),
                                "text": text,
                            },
                        )
                    )
                    point_id += 1
                    self._chunk_count += 1

        if points:
            self._client.upsert(collection_name=self._COLLECTION, points=points)

    def execute(self, query: str, top_k: int = 5) -> ToolResult:
        try:
            self._init_rag()
            qm = _qdrant_models()
            dense_vec = list(_dense_model().embed([query]))[0].tolist()

            sparse_emb = list(_sparse_model().embed([query]))[0]
            sparse_vec = qm.SparseVector(
                indices=sparse_emb.indices.tolist(),
                values=sparse_emb.values.tolist(),
            )

            # Hybrid query: dense + BM25 fused with Reciprocal Rank Fusion.
            # Prefetch casts a wider net (4× top_k) before RRF re-ranks.
            results = self._client.query_points(
                collection_name=self._COLLECTION,
                prefetch=[
                    qm.Prefetch(query=dense_vec, using="dense", limit=top_k * 4),
                    qm.Prefetch(query=sparse_vec, using="sparse", limit=top_k * 4),
                ],
                query=qm.FusionQuery(fusion=qm.Fusion.RRF),
                limit=top_k,
                with_payload=True,
            )

            hits = []
            for pt in results.points:
                p = pt.payload
                hits.append(
                    f"FILE: {p['file']}\n"
                    f"LINES: {p['start_line']}-{p['end_line']}\n"
                    f"SNIPPET:\n{p['text'].strip()}"
                )

            output = "\n\n---\n\n".join(hits) if hits else "No relevant context found."
            return self.format_result(output)
        except Exception as e:
            return self.format_result(f"Error in SimpleRag: {e}")
