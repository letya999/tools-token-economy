#!/usr/bin/env python3
"""Smoke test for grep family tools."""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.features.tool_registry.grep_tools import AstGrepTool, GitGrepTool, GrepTool, RgTool, UgrepTool


def _init_git_repo(path: str) -> None:
    for cmd in [
        ["git", "init", "-q"],
        ["git", "config", "user.email", "smoke@test.com"],
        ["git", "config", "user.name", "Smoke Test"],
        ["git", "add", "."],
        ["git", "commit", "-m", "init", "-q"],
    ]:
        subprocess.run(cmd, cwd=path, capture_output=True, check=True)


def main() -> int:
    failed = False

    with tempfile.TemporaryDirectory() as tmp:
        test_file = os.path.join(tmp, "sample.py")
        with open(test_file, "w") as f:
            f.write("def hello():\n    pass\n")
        _init_git_repo(tmp)

        checks = [
            ("GrepTool", GrepTool(tmp).execute(pattern="hello")),
            ("RgTool", RgTool(tmp).execute(pattern="hello")),
            ("UgrepTool", UgrepTool(tmp).execute(pattern="hello")),
            ("GitGrepTool", GitGrepTool(tmp).execute(pattern="hello")),
        ]
        for name, res in checks:
            if "Error:" in res.output or "hello" not in res.output:
                print(f"[FAIL] {name}: {res.output[:200]}", file=sys.stderr)
                failed = True
            else:
                print(f"[OK] {name}")

        # ast-grep: no match is acceptable, Error is not
        res = AstGrepTool(tmp).execute(pattern="def $A(): ...")
        if "Error:" in res.output and "no matches" not in res.output.lower():
            print(f"[FAIL] AstGrepTool: {res.output[:200]}", file=sys.stderr)
            failed = True
        else:
            print("[OK] AstGrepTool")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
