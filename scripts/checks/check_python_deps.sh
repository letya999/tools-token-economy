#!/bin/bash
PYTHON="${VENV_PYTHON:-python3}"
$PYTHON -c "
import importlib.util, sys
REQUIRED = ['qdrant_client', 'fastembed', 'jedi', 'tree_sitter', 'serena']
missing = [p for p in REQUIRED if importlib.util.find_spec(p) is None]
if missing:
    print('Missing packages:', missing, file=sys.stderr)
    sys.exit(1)
"
