#!/usr/bin/env python3
"""Smoke test for SimpleRagTool (Qdrant + fastembed)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.features.tool_registry.semantic_tools import SimpleRagTool


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        for name, content in [
            ("auth.py", "def authenticate_user(token):\n    pass\n"),
            ("utils.py", "def parse_config(path):\n    pass\n"),
            ("models.py", "class UserModel:\n    pass\n"),
        ]:
            with open(os.path.join(tmp, name), "w") as f:
                f.write(content)

        res = SimpleRagTool(tmp).execute(query="function definition")
        if "Error" in res.output:
            print(f"[FAIL] SimpleRagTool: {res.output[:300]}", file=sys.stderr)
            return 1

        print(f"[OK] SimpleRagTool — returned {res.tokens} tokens")
        return 0


if __name__ == "__main__":
    sys.exit(main())
