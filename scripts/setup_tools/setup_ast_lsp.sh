#!/bin/bash
set -e
VENV="/mnt/c/Users/User/a_projects/tools_token_economy/.venv-wsl"
PY="$VENV/bin/python"

echo "=== Tree-sitter Python bindings ==="
$PY -c "import tree_sitter" 2>/dev/null || $VENV/bin/pip install tree-sitter
$PY -c "import tree_sitter_python" 2>/dev/null || $VENV/bin/pip install tree-sitter-python
# Verify the exact imports used by structural_tools.py
$PY -c "
import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Query, QueryCursor
lang = Language(tspython.language())
parser = Parser(lang)
tree = parser.parse(b'def hello_world(): pass\nclass Foo: pass\n')
query = Query(lang, '(function_definition name: (identifier) @fn)')
cursor = QueryCursor(query)
captures = cursor.captures(tree.root_node)
assert captures, 'query returned no captures'
print('[OK] tree-sitter python grammar: captures =', list(captures.keys()))
" || { echo '[FAIL] tree-sitter-python not working correctly'; exit 1; }

echo "=== LSP (jedi) ==="
$PY -c "import jedi; print('[OK] jedi', jedi.__version__)"
# Smoke test against a real Python file
$PY -c "
import jedi
script = jedi.Script('import os\nos.path.')
completions = script.complete(2, 9)
assert len(completions) > 0, 'jedi returned no completions'
print('[OK] jedi completions working:', len(completions), 'results')
"

echo "=== AST grep ==="
which ast-grep || { echo '[FAIL] ast-grep not in PATH'; exit 1; }
ast-grep --version && echo '[OK] ast-grep'

echo "AST and LSP setup complete."
