#!/usr/bin/env python3
"""Smoke test for basic file tools: read, write, patch, glob."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.features.tool_registry.basic_tools import FileReadTool, FileWriteTool, GlobTool, PatchApplierTool


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        test_file = os.path.join(tmp, "test.py")
        with open(test_file, "w") as f:
            f.write("def hello():\n    pass\n")

        # read
        res = FileReadTool(tmp).execute(file_path="test.py")
        if not res.output or "Error:" in res.output:
            print(f"[FAIL] FileReadTool: {res.output}", file=sys.stderr)
            return 1
        print("[OK] FileReadTool")

        # write
        res = FileWriteTool(tmp).execute(file_path="out.py", content="x = 1\n")
        if "Error:" in res.output:
            print(f"[FAIL] FileWriteTool: {res.output}", file=sys.stderr)
            return 1
        print("[OK] FileWriteTool")

        # patch
        patch = (
            "--- a/test.py\n+++ b/test.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def hello():\n"
            "-    pass\n"
            "+    return 42\n"
        )
        res = PatchApplierTool(tmp).execute(patch=patch)
        if "Error:" in res.output:
            print(f"[FAIL] PatchApplierTool: {res.output}", file=sys.stderr)
            return 1
        print("[OK] PatchApplierTool")

        # glob
        res = GlobTool(tmp).execute(pattern="*.py")
        if not res.output or "Error:" in res.output:
            print(f"[FAIL] GlobTool: {res.output}", file=sys.stderr)
            return 1
        print("[OK] GlobTool")

    return 0


if __name__ == "__main__":
    sys.exit(main())
