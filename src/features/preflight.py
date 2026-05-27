"""
Pre-flight environment validation for the benchmark runner.

Checks are split into two levels:
  critical - failure blocks the benchmark from starting
  warning  - failure is logged but execution continues
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Literal

from src.core.models import AgentConfig

_log = logging.getLogger(__name__)

# Maps tool name in configs -> CLI binary required (None = pure-Python, no CLI)
_TOOL_CLI_DEPS: dict[str, str | None] = {
    "read": None,
    "read_all": None,
    "write": None,
    "patch": None,
    "glob": None,
    "tree_sitter": None,
    "repo_map": None,
    "simple_rag": None,
    "lsp_symbols": None,
    "serena": "serena",
    "semble": "uvx",
    "grep": "grep",
    "git_grep": "git",
    "rg": "rg",
    "ugrep": "ugrep",
    "ast_grep": "ast-grep",
    "semgrep": "semgrep",
    "shell": None,
}

# API key env-var names per model pattern
_MODEL_KEY_MAP: list[tuple[str, list[str]]] = [
    ("gemini", ["GOOGLE_API_KEY", "GEMINI_API_KEY"]),
    ("google/", ["GOOGLE_API_KEY", "GEMINI_API_KEY"]),
    ("gpt-", ["OPENAI_API_KEY"]),
    ("openai/", ["OPENAI_API_KEY"]),
    ("claude-", ["ANTHROPIC_API_KEY"]),
    ("anthropic/", ["ANTHROPIC_API_KEY"]),
    ("openrouter/", ["OPENROUTER_API_KEY"]),
]


@dataclass
class PreflightResult:
    name: str
    passed: bool
    level: Literal["critical", "warning", "info"]
    detail: str = ""


@dataclass
class PreflightReport:
    results: list[PreflightResult] = field(default_factory=list)

    @property
    def all_critical_passed(self) -> bool:
        return all(r.passed for r in self.results if r.level == "critical")

    def add(self, result: PreflightResult) -> None:
        self.results.append(result)

    def print_summary(self) -> None:
        width = 60
        print(f"\n{'=' * width}")
        print("  PRE-FLIGHT CHECK REPORT")
        print(f"{'=' * width}")
        for r in self.results:
            status = "PASS" if r.passed else ("FAIL" if r.level == "critical" else "WARN")
            tag = f"[{status}]"
            line = f"  {tag:<8} {r.name}"
            if r.detail:
                line += f"\n           {r.detail}"
            print(line)
        print(f"{'=' * width}")
        if self.all_critical_passed:
            print("  All critical checks passed. Starting benchmark.")
        else:
            print("  CRITICAL checks FAILED. Benchmark aborted.")
        print(f"{'=' * width}\n")


class PreflightChecker:
    """
    Runs all pre-flight checks and raises PreflightError if any critical check fails.
    """

    def __init__(
        self,
        repo_path: str,
        configs: list[AgentConfig],
        test_cmd: str,
        dry_run: bool = False,
        selected_ids: list[str] | None = None,
    ):
        self.repo_path = os.path.abspath(repo_path)
        self.test_cmd = test_cmd
        self.dry_run = dry_run

        # Only check deps for configs that will actually run
        if selected_ids:
            self.configs = [c for c in configs if c.id in selected_ids]
        else:
            self.configs = configs

    def run(self) -> PreflightReport:
        report = PreflightReport()

        for check in [
            self._check_benchmark_python,
            self._check_git,
            self._check_python_packages,
            self._check_tool_cli_deps,
            self._check_tool_smoke_tests,
            self._check_api_keys,
            self._check_target_repo,
            self._check_target_deps,
        ]:
            results = check()
            for r in results:
                report.add(r)

        report.print_summary()

        if not report.all_critical_passed:
            raise PreflightError("Pre-flight checks failed. See report above.")

        return report

    # ------------------------------------------------------------------
    # Individual check groups
    # ------------------------------------------------------------------

    def _check_benchmark_python(self) -> list[PreflightResult]:
        version = sys.version_info
        ok = version >= (3, 13)
        return [PreflightResult(
            name="Python >= 3.13",
            passed=ok,
            level="critical",
            detail=f"Found {version.major}.{version.minor}.{version.micro}" + ("" if ok else " — upgrade required"),
        )]

    def _check_python_packages(self) -> list[PreflightResult]:
        """Check that key Python packages are importable."""
        import importlib.util

        needed_tools: set[str] = set()
        for config in self.configs:
            needed_tools.update(config.tools)

        # (import_name, pip_name, required_by_tools)
        package_specs = [
            ("qdrant_client", "qdrant-client", {"simple_rag"}),
            ("fastembed", "fastembed", {"simple_rag"}),
            ("jedi", "jedi", {"lsp_symbols"}),
            ("tree_sitter", "tree-sitter", {"tree_sitter"}),
            # tree_sitter_python ships the pre-compiled Python grammar (separate from the engine)
            ("tree_sitter_python", "tree-sitter-python", {"tree_sitter"}),
        ]

        results = []
        for pkg, pip_name, required_by in package_specs:
            found = importlib.util.find_spec(pkg) is not None
            is_needed = bool(needed_tools & required_by)
            level = "critical" if is_needed else "warning"
            results.append(PreflightResult(
                name=f"Python package: {pkg}",
                passed=found,
                level=level,
                detail="Import successful" if found else f"`{pkg}` not found — install via `pip install {pip_name}`",
            ))
        return results

    def _check_git(self) -> list[PreflightResult]:
        found = shutil.which("git") is not None
        return [PreflightResult(
            name="git in PATH",
            passed=found,
            level="critical",
            detail="" if found else "Install Git for Windows or git package",
        )]

    def _check_tool_cli_deps(self) -> list[PreflightResult]:
        needed_clis: set[str] = set()
        for config in self.configs:
            for tool_name in config.tools:
                cli = _TOOL_CLI_DEPS.get(tool_name)
                if cli:
                    needed_clis.add(cli)

        # git already checked above — skip duplicate
        needed_clis.discard("git")

        results = []
        for cli in sorted(needed_clis):
            found = shutil.which(cli) is not None
            results.append(PreflightResult(
                name=f"CLI tool: {cli}",
                passed=found,
                level="critical",
                detail="" if found else f"Required by active config tools. Install `{cli}`.",
            ))
        return results

    def _check_tool_smoke_tests(self) -> list[PreflightResult]:
        """Verify that each tool actually functions by running a tiny search/analyze."""
        results = []
        needed_tools = set()
        for config in self.configs:
            for tool_name in config.tools:
                needed_tools.add(tool_name)

        if not needed_tools:
            return results

        with tempfile.TemporaryDirectory() as tmp_dir:
            test_file = os.path.join(tmp_dir, "test_smoke.py")
            with open(test_file, "w") as f:
                f.write("def hello_world():\n    pass\n")

            # Initialize git for git_grep
            subprocess.run(["git", "init", "-q"], cwd=tmp_dir)
            subprocess.run(["git", "add", "test_smoke.py"], cwd=tmp_dir)
            subprocess.run(["git", "config", "user.email", "smoke@test.com"], cwd=tmp_dir)
            subprocess.run(["git", "config", "user.name", "Smoke Test"], cwd=tmp_dir)
            subprocess.run(["git", "commit", "-m", "init", "-q"], cwd=tmp_dir)

            from src.features.tool_registry.grep_tools import GrepTool, GitGrepTool, RgTool, UgrepTool, AstGrepTool, SemgrepTool
            from src.features.tool_registry.structural_tools import TreeSitterTool
            from src.features.tool_registry.lsp_tools import LspSymbolsTool

            smoke_checks = {
                "grep": (GrepTool, "hello_world"),
                "git_grep": (GitGrepTool, "hello_world"),
                "rg": (RgTool, "hello_world"),
                "ugrep": (UgrepTool, "hello_world"),
                "ast_grep": (AstGrepTool, "print($A)"),
                "semgrep": (SemgrepTool, "def hello_world"),
                "tree_sitter": (TreeSitterTool, "test_smoke.py"),
                "lsp_symbols": (LspSymbolsTool, "hello_world"),
            }

            for tool_name in sorted(needed_tools):
                if tool_name not in smoke_checks:
                    continue
                
                tool_class, arg = smoke_checks[tool_name]
                try:
                    tool_inst = tool_class(tmp_dir)
                    if tool_name == "tree_sitter":
                        res = tool_inst.execute(file_path=arg)
                    elif tool_name == "lsp_symbols":
                        res = tool_inst.execute(symbol=arg)
                    else:
                        res = tool_inst.execute(pattern=arg)
                    
                    output = str(res.output)
                    passed = "Error:" not in output and "No matches found" not in output and len(output) > 2
                    
                    # For structural search tools: no matches is still a successful run.
                    if tool_name in ("semgrep", "ast_grep") and "No matches found" in output:
                        passed = True

                    results.append(PreflightResult(
                        name=f"Smoke test: {tool_name}",
                        passed=passed,
                        level="warning",
                        detail="" if passed else f"Tool returned unexpected output: {output[:100]}",
                    ))
                except Exception as e:
                    results.append(PreflightResult(
                        name=f"Smoke test: {tool_name}",
                        passed=False,
                        level="warning",
                        detail=f"Tool execution failed: {e}",
                    ))

        return results

    def _check_api_keys(self) -> list[PreflightResult]:
        required_vars: dict[str, list[str]] = {}

        for config in self.configs:
            m = config.model.lower()
            for prefix, env_vars in _MODEL_KEY_MAP:
                if prefix in m:
                    key = env_vars[0]
                    required_vars.setdefault(key, env_vars)
                    break

        results = []
        for primary_var, candidates in required_vars.items():
            found = any(os.getenv(v) for v in candidates)
            # In dry-run mode no real API calls are made, so missing keys are non-fatal.
            level = "warning" if self.dry_run else "critical"
            results.append(PreflightResult(
                name=f"API key: {primary_var}",
                passed=found,
                level=level,
                detail="" if found else f"Set one of: {', '.join(candidates)}",
            ))
        return results

    def _check_target_repo(self) -> list[PreflightResult]:
        results = []

        exists = os.path.isdir(self.repo_path)
        results.append(PreflightResult(
            name="Target repo exists",
            passed=exists,
            level="critical",
            detail=self.repo_path if exists else f"Not found: {self.repo_path}",
        ))
        if not exists:
            return results

        git_dir = os.path.join(self.repo_path, ".git")
        is_git = os.path.isdir(git_dir)
        results.append(PreflightResult(
            name="Target repo is git",
            passed=is_git,
            level="critical",
            detail="" if is_git else f"No .git directory at {self.repo_path}",
        ))

        return results

    def _check_target_deps(self) -> list[PreflightResult]:
        """Ensure target repo venv dependencies are installed via uv sync."""
        results = []

        pyproject = os.path.join(self.repo_path, "pyproject.toml")
        requirements = os.path.join(self.repo_path, "requirements.txt")

        has_pyproject = os.path.isfile(pyproject)
        has_requirements = os.path.isfile(requirements)

        if not has_pyproject and not has_requirements:
            results.append(PreflightResult(
                name="Target repo deps",
                passed=True,
                level="info",
                detail="No pyproject.toml or requirements.txt found — skipping dep install",
            ))
            return results

        # Prefer uv if available and pyproject.toml exists
        if has_pyproject and shutil.which("uv"):
            results.append(self._run_uv_sync())
        elif has_requirements and shutil.which("pip"):
            results.append(self._run_pip_install(requirements))
        else:
            results.append(PreflightResult(
                name="Target repo deps",
                passed=False,
                level="warning",
                detail="Found pyproject.toml but neither `uv` nor `pip` available to install deps",
            ))

        return results

    def _extract_uv_extras(self) -> list[str]:
        """Parse --extra <name> flags from the test_cmd string."""
        import shlex as _shlex
        extras: list[str] = []
        try:
            tokens = _shlex.split(self.test_cmd)
        except ValueError:
            return extras
        i = 0
        while i < len(tokens):
            if tokens[i] == "--extra" and i + 1 < len(tokens):
                extras.append(tokens[i + 1])
                i += 2
            elif tokens[i].startswith("--extra="):
                extras.append(tokens[i].split("=", 1)[1])
                i += 1
            else:
                i += 1
        return extras

    def _run_uv_sync(self) -> PreflightResult:
        extras = self._extract_uv_extras()
        cmd = ["uv", "sync"]
        for extra in extras:
            cmd += ["--extra", extra]
        _log.info("Running `%s` in target repo: %s", " ".join(cmd), self.repo_path)
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode == 0:
                extra_str = f" (extras: {', '.join(extras)})" if extras else ""
                return PreflightResult(
                    name="Target repo deps (uv sync)",
                    passed=True,
                    level="critical",
                    detail=f"Dependencies installed/verified via uv sync{extra_str}",
                )
            return PreflightResult(
                name="Target repo deps (uv sync)",
                passed=False,
                level="critical",
                detail=f"uv sync failed (exit {proc.returncode}): {proc.stderr.strip()[:200]}",
            )
        except subprocess.TimeoutExpired:
            return PreflightResult(
                name="Target repo deps (uv sync)",
                passed=False,
                level="critical",
                detail="uv sync timed out after 120s",
            )
        except Exception as exc:
            return PreflightResult(
                name="Target repo deps (uv sync)",
                passed=False,
                level="critical",
                detail=f"uv sync error: {exc}",
            )

    def _run_pip_install(self, requirements_path: str) -> PreflightResult:
        _log.info("Running pip install -r requirements.txt in %s", self.repo_path)
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", requirements_path, "-q"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if proc.returncode == 0:
                return PreflightResult(
                    name="Target repo deps (pip install)",
                    passed=True,
                    level="warning",
                    detail="Dependencies installed via pip",
                )
            return PreflightResult(
                name="Target repo deps (pip install)",
                passed=False,
                level="warning",
                detail=f"pip install failed: {proc.stderr.strip()[:200]}",
            )
        except Exception as exc:
            return PreflightResult(
                name="Target repo deps (pip install)",
                passed=False,
                level="warning",
                detail=f"pip install error: {exc}",
            )


class PreflightError(RuntimeError):
    """Raised when one or more critical pre-flight checks fail."""
