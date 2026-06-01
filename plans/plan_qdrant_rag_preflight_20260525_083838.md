# Plan: Qdrant RAG + Preflight Hardening + Guaranteed Install Flow

## Goal
1. Replace BM25 SimpleRagTool with real vector RAG (Qdrant in-memory + fastembed).
2. Remove SimpleRag fallback from SerenaAdapterTool and SembleAdapterTool — they must fail explicitly.
3. Add preflight checks for serena, semble CLI, qdrant-client, fastembed.
4. Add `scripts/setup_semantic_tools.sh` for guaranteed installation of all semantic tool deps.
5. Update `run_benchmark_wsl.sh` to run setup scripts before the benchmark.
6. Add qdrant-client and fastembed to pyproject.toml dependencies.

---

## Files to Modify

### 1. `src/features/tool_registry/semantic_tools.py` — FULL REWRITE

**SimpleRagTool** — replace BM25 with Qdrant in-memory + fastembed:
- Imports: `from qdrant_client import QdrantClient, models` and `from fastembed import TextEmbedding`
- Lazy init: `_client` and `_model` built on first `execute()` call, cached on self.
- `_build_index()`:
  - Walk all `.py` files in worktree (skip `.venv`, `__pycache__`, `.git`)
  - Read each file, chunk into ~50-line windows with 10-line overlap
  - Generate embeddings via `TextEmbedding(model_name="BAAI/bge-small-en-v1.5")`
  - Create in-memory QdrantClient, collection name `"rag"`, vector size 384 (bge-small)
  - Upsert all chunks as points with payload `{file: rel_path, start_line: int, text: str}`
- `execute(query: str, top_k: int = 5) -> ToolResult`:
  - Embed query
  - `client.search(collection_name="rag", query_vector=..., limit=top_k)`
  - Return formatted results: `FILE: path\nLINES: start-end\nSNIPPET: text`

**SerenaAdapterTool** — remove fallback:
- Delete `self.rag_engine = SimpleRagTool(...)` line
- In `execute()`: remove the `except Exception: return self.rag_engine.execute(...)` fallback
- Instead: `except Exception as e: return self.format_result(f"Error: Serena MCP unavailable: {e}")`

**SembleAdapterTool** — remove fallback:
- Same as Serena: delete `self.rag_engine`, replace fallback with explicit error message.

---

### 2. `pyproject.toml` — Add dependencies

In `[project] dependencies` list, add:
```
"qdrant-client>=1.9.0",
"fastembed>=0.3.6",
```

---

### 3. `src/features/preflight.py` — Add new checks

**In `_TOOL_CLI_DEPS`** — add serena and semble CLI mappings:
```python
"serena": "serena",    # was None
"semble": "semble",    # was None
```
These become critical preflight checks when those tools are in an active config.

**Add `_check_python_packages()` method** — checks that key Python packages are importable:
- `qdrant_client` (required by simple_rag)
- `fastembed` (required by simple_rag)
- Failures are level="critical" if the tool is in active configs, "warning" otherwise.

Add this check to the `run()` method's check list, between `_check_tool_cli_deps` and `_check_tool_smoke_tests`.

**In `_TOOL_CLI_DEPS`** — note: keeping `"simple_rag": None` (no CLI dep, Python-only). The package check covers it.

---

### 4. `scripts/setup_semantic_tools.sh` — NEW FILE

```bash
#!/bin/bash
# Guaranteed install of semantic tool dependencies
# Run from WSL: bash scripts/setup_semantic_tools.sh
set -e

VENV_PYTHON="/mnt/c/Users/User/a_projects/tools_token_economy/.venv-wsl/bin/python"

echo "=== Installing semantic tool dependencies ==="

# 1. Serena MCP — needed for serena tool
if ! command -v serena &>/dev/null; then
    echo "Installing serena-agent..."
    $VENV_PYTHON -m pip install serena-agent
else
    echo "serena: OK ($(serena --version 2>/dev/null || echo installed))"
fi

# 2. Qdrant client + fastembed — needed for simple_rag tool
echo "Installing qdrant-client and fastembed..."
$VENV_PYTHON -m pip install "qdrant-client>=1.9.0" "fastembed>=0.3.6"

# 3. Verify imports
$VENV_PYTHON -c "import qdrant_client; print('qdrant-client: OK', qdrant_client.__version__)"
$VENV_PYTHON -c "import fastembed; print('fastembed: OK', fastembed.__version__)"

echo "=== Semantic tool setup complete ==="
```

---

### 5. `run_benchmark_wsl.sh` — Add setup step before main.py

Current content:
```bash
#!/bin/bash
set -e
export PATH="$HOME/.local/bin:$PATH"
source /mnt/c/Users/User/a_projects/tools_token_economy/.venv-wsl/bin/activate
cd /mnt/c/Users/User/a_projects/tools_token_economy
exec python main.py
```

Replace with (add setup steps before exec):
```bash
#!/bin/bash
set -e
export PATH="$HOME/.local/bin:$PATH"
source /mnt/c/Users/User/a_projects/tools_token_economy/.venv-wsl/bin/activate
cd /mnt/c/Users/User/a_projects/tools_token_economy

echo "=== Step 1: Installing tool dependencies ==="
bash scripts/setup_tools/install_grep_family.sh
bash scripts/setup_semantic_tools.sh

echo "=== Step 2: Dry run preflight check ==="
python main.py --dry-run

echo "=== Step 3: Running benchmark ==="
exec python main.py
```

---

### 6. `scripts/setup_tools/install_grep_family.sh` — Fix ast-grep install

Current: `pip install ast-grep-cli` (breaks under PEP 668, installs as `sg` not `ast-grep`)

Replace the ast-grep block with:
```bash
# ast-grep binary from GitHub releases (provides both `sg` and `ast-grep`)
if ! command -v ast-grep &>/dev/null; then
    echo "Downloading ast-grep binary from GitHub releases..."
    LATEST=$(curl -sL https://api.github.com/repos/ast-grep/ast-grep/releases/latest | python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'])")
    curl -sL "https://github.com/ast-grep/ast-grep/releases/download/${LATEST}/app-x86_64-unknown-linux-gnu.zip" -o /tmp/ast-grep.zip
    python3 -c "import zipfile; zipfile.ZipFile('/tmp/ast-grep.zip').extractall('/tmp/ast-grep-extracted/')"
    mkdir -p ~/.local/bin
    cp /tmp/ast-grep-extracted/ast-grep ~/.local/bin/ast-grep
    cp /tmp/ast-grep-extracted/sg ~/.local/bin/sg
    chmod +x ~/.local/bin/ast-grep ~/.local/bin/sg
    rm -rf /tmp/ast-grep.zip /tmp/ast-grep-extracted
    echo "ast-grep: OK ($(ast-grep --version))"
else
    echo "ast-grep: OK ($(ast-grep --version))"
fi
```

---

## Implementation Notes

- `fastembed` downloads the BAAI/bge-small-en-v1.5 model (~80MB ONNX) on first use and caches it in `~/.cache/fastembed/`. This is expected behavior.
- Qdrant in-memory client (`QdrantClient(":memory:")`) creates a fresh store per `SimpleRagTool` instance — no persistence between runs, which is correct for per-worktree isolation.
- The `--dry-run` flag in main.py passes through to `BenchmarkOrchestrator(dry_run=True)` which skips most preflight. We want the REAL preflight on dry-run to catch missing tools BEFORE the benchmark. Check main.py argument handling — `--dry-run` should run preflight normally, only skip the actual agent execution.
- If `semble` has no public pip package yet, its preflight check level should be "warning" not "critical" — add a comment noting this.

## Order of Implementation
1. pyproject.toml (add deps)
2. semantic_tools.py (Qdrant RAG + remove fallbacks)  
3. preflight.py (add Python package checks + serena/semble CLI checks)
4. scripts/setup_semantic_tools.sh (new file)
5. scripts/setup_tools/install_grep_family.sh (fix ast-grep install)
6. run_benchmark_wsl.sh (add setup steps)
7. Run: `uv sync` in .venv-wsl to pick up new deps
