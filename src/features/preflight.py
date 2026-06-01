"""
Pre-flight environment validation for the benchmark runner.

Checks are split into two levels:
  critical - failure blocks the benchmark from starting
  warning  - failure is logged but execution continues
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Literal

from src.core.models import AgentConfig, ProviderConfig

_log = logging.getLogger(__name__)


def _wsl_path() -> str:
    """Return PATH string enriched with common local bin dirs for WSL/Linux."""
    if sys.platform == "win32":
        return os.environ.get("PATH", "")
    extra = [
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/.cargo/bin"),
        "/usr/local/bin",
    ]
    base = os.environ.get("PATH", "")
    additions = [d for d in extra if os.path.isdir(d) and d not in base]
    return ":".join(additions + [base]) if additions else base


def _wsl_which(binary: str) -> str | None:
    """Find a binary, checking common WSL local bin dirs if not in current PATH."""
    found = shutil.which(binary)
    if found:
        return found
    if sys.platform == "win32":
        return None
    for d in [os.path.expanduser("~/.local/bin"), os.path.expanduser("~/.cargo/bin"), "/usr/local/bin"]:
        candidate = os.path.join(d, binary)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _enrich_path() -> None:
    """Prepend ~/.local/bin and ~/.cargo/bin to os.environ['PATH'] if missing (WSL/Linux only)."""
    if sys.platform == "win32":
        return
    enriched = _wsl_path()
    if enriched != os.environ.get("PATH", ""):
        os.environ["PATH"] = enriched

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
        target_file: str | None = None,
        target_test: str | None = None,
        required_files: list[str] | None = None,
        provider_cfg: ProviderConfig | None = None,
    ):
        self.repo_path = os.path.abspath(repo_path)
        self.test_cmd = test_cmd
        self.dry_run = dry_run
        self.target_file = target_file
        self.target_test = target_test
        self.required_files = required_files or []
        self.provider_cfg = provider_cfg

        # Only check deps for configs that will actually run
        if selected_ids:
            self.configs = [c for c in configs if c.id in selected_ids]
        else:
            self.configs = configs

    def run(self) -> PreflightReport:
        _enrich_path()
        report = PreflightReport()

        for check in [
            self._check_benchmark_python,
            self._check_git,
            self._check_python_packages,
            self._check_tool_cli_deps,
            self._check_tool_smoke_tests,
            self._check_api_keys,
            self._check_models_exist,
            self._check_target_repo,
            self._check_target_deps,
            self._check_target_file_and_baseline,
            self._check_required_files,
            self._check_serena_global_config,
            self._check_semble_model,
            self._check_fastembed_model,
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
            found = _wsl_which(cli) is not None
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

    def _check_models_exist(self) -> list[PreflightResult]:
        """Verify that the agent and judge models actually exist on the provider platforms."""
        if self.dry_run:
            return [PreflightResult(
                name="Model existence checks",
                passed=True,
                level="info",
                detail="Skipped in dry-run mode",
            )]

        if not self.provider_cfg:
            return []

        # Collect unique (provider, model, api_key_env) to check
        to_check = []
        # Agent model
        to_check.append((self.provider_cfg.provider, self.provider_cfg.model, self.provider_cfg.api_key_env))
        # Judge model
        to_check.append((self.provider_cfg.judge.provider, self.provider_cfg.judge.model, self.provider_cfg.judge.api_key_env))

        # Filter duplicates
        seen = set()
        unique_checks = []
        for p, m, k in to_check:
            if (p, m) not in seen:
                unique_checks.append((p, m, k))
                seen.add((p, m))

        results = []
        for provider, model_id, api_key_env in unique_checks:
            if provider == "openai":
                results.append(self._verify_openai_model(model_id, api_key_env))
            elif provider == "anthropic":
                results.append(self._verify_anthropic_model(model_id, api_key_env))
            else:
                results.append(PreflightResult(
                    name=f"Model check: {model_id}",
                    passed=True,
                    level="info",
                    detail=f"Verification not implemented for provider '{provider}'",
                ))
        return results

    def _verify_openai_model(self, model_id: str, api_key_env: str) -> PreflightResult:
        import openai as _openai
        api_key = os.getenv(api_key_env)
        if not api_key:
            return PreflightResult(
                name=f"Model exists: {model_id}",
                passed=False,
                level="critical",
                detail=f"Missing API key '{api_key_env}' to verify model",
            )
        
        try:
            client = _openai.OpenAI(api_key=api_key)
            client.models.retrieve(model_id)
            return PreflightResult(
                name=f"Model exists: {model_id}",
                passed=True,
                level="critical",
                detail="OK",
            )
        except _openai.NotFoundError:
            return PreflightResult(
                name=f"Model exists: {model_id}",
                passed=False,
                level="critical",
                detail=f"Model '{model_id}' not found on OpenAI. Check provider.yaml.",
            )
        except Exception as e:
            return PreflightResult(
                name=f"Model exists: {model_id}",
                passed=False,
                level="critical",
                detail=f"Could not verify model '{model_id}': {e}",
            )

    def _verify_anthropic_model(self, model_id: str, api_key_env: str) -> PreflightResult:
        # Anthropic doesn't have a simple 'retrieve' but we can list and check
        import anthropic as _anthropic
        api_key = os.getenv(api_key_env)
        if not api_key:
            return PreflightResult(
                name=f"Model exists: {model_id}",
                passed=False,
                level="critical",
                detail=f"Missing API key '{api_key_env}' to verify model",
            )
        
        try:
            client = _anthropic.Anthropic(api_key=api_key)
            models = client.models.list()
            ids = [m.id for m in models.data]
            if model_id in ids:
                 return PreflightResult(
                    name=f"Model exists: {model_id}",
                    passed=True,
                    level="critical",
                    detail="OK",
                )
            return PreflightResult(
                name=f"Model exists: {model_id}",
                passed=False,
                level="critical",
                detail=f"Model '{model_id}' not found on Anthropic. Check provider.yaml.",
            )
        except Exception as e:
            return PreflightResult(
                name=f"Model exists: {model_id}",
                passed=False,
                level="critical",
                detail=f"Could not verify model '{model_id}': {e}",
            )

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

    def _check_target_file_and_baseline(self) -> list[PreflightResult]:
        results = []
        
        # Check target_file exists
        if self.target_file:
            full_path = os.path.join(self.repo_path, self.target_file)
            exists = os.path.isfile(full_path)
            results.append(PreflightResult(
                name=f"Target file exists: {self.target_file}",
                passed=exists,
                level="critical",
                detail=full_path if exists else f"NOT FOUND: {full_path}",
            ))
            if not exists:
                return results
        
        # Run baseline test count on specific test file
        if self.target_test and shutil.which("uv"):
            test_file_path = os.path.join(self.repo_path, self.target_test)
            if os.path.isfile(test_file_path):
                cmd = f"uv run --extra dev pytest {self.target_test} -q --no-header"
                try:
                    proc = subprocess.run(
                        cmd, shell=True, cwd=self.repo_path,
                        capture_output=True, text=True, timeout=120
                    )
                    output = proc.stdout + proc.stderr
                    pass_match = re.search(r"(\d+) passed", output)
                    baseline_count = int(pass_match.group(1)) if pass_match else 0
                    passed = baseline_count > 0
                    results.append(PreflightResult(
                        name=f"Baseline tests in {self.target_test}",
                        passed=passed,
                        level="critical" if not passed else "info",
                        detail=f"Baseline: {baseline_count} tests pass" + ("" if passed else " — 0 baseline tests, check target file"),
                    ))
                except Exception as e:
                    results.append(PreflightResult(
                        name=f"Baseline tests in {self.target_test}",
                        passed=False,
                        level="warning",
                        detail=f"Could not run baseline: {e}",
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
        # Strip UV_PROJECT_ENVIRONMENT so target repo creates its own venv,
        # not reusing (and overwriting) the benchmark's venv.
        _env = os.environ.copy()
        _env.pop("UV_PROJECT_ENVIRONMENT", None)
        _env.pop("UV_LINK_MODE", None)
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=120,
                env=_env,
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


    def _check_serena_global_config(self) -> list[PreflightResult]:
        """Verify ~/.serena/serena_config.yml exists (absence causes Serena pydantic ValidationError)."""
        needs_serena = any("serena" in c.tools for c in self.configs)
        if not needs_serena:
            return []
        cfg = os.path.join(os.path.expanduser("~"), ".serena", "serena_config.yml")
        exists = os.path.isfile(cfg)
        return [PreflightResult(
            name="Serena: global config",
            passed=exists,
            level="critical",
            detail=cfg if exists else f"Missing {cfg} — run: serena init  (or bash scripts/install/install_serena.sh)",
        )]

    def _check_semble_model(self) -> list[PreflightResult]:
        """Verify minishlab/potion-code-16M is fully cached; download it if incomplete."""
        needs_semble = any("semble" in c.tools for c in self.configs)
        if not needs_semble:
            return []

        model_id = "minishlab/potion-code-16M"
        hf_cache = os.path.expanduser("~/.cache/huggingface/hub")
        snap_base = os.path.join(hf_cache, "models--minishlab--potion-code-16M", "snapshots")

        if os.path.isdir(snap_base):
            for snap in os.listdir(snap_base):
                snap_dir = os.path.join(snap_base, snap)
                if not os.path.isdir(snap_dir):
                    continue
                real_files = [f for f in os.listdir(snap_dir) if not f.startswith(".")]
                if real_files:
                    return [PreflightResult(
                        name="Semble: potion-code-16M model",
                        passed=True,
                        level="info",
                        detail=f"Model '{model_id}' cached ({len(real_files)} files in {snap_dir})",
                    )]

        # Model missing or incomplete — clean up and re-download.
        blobs_dir = os.path.join(hf_cache, "models--minishlab--potion-code-16M", "blobs")
        if os.path.isdir(blobs_dir):
            for fname in os.listdir(blobs_dir):
                if fname.endswith(".incomplete"):
                    try:
                        os.remove(os.path.join(blobs_dir, fname))
                        _log.info("Removed incomplete blob: %s", fname)
                    except Exception:
                        pass

        uvx = _wsl_which("uvx")
        if not uvx:
            return [PreflightResult(
                name="Semble: potion-code-16M model",
                passed=False,
                level="warning",
                detail="uvx not found — cannot download model. Run: bash scripts/install/install_semble.sh",
            )]

        _log.info("Downloading semble model '%s' via uvx...", model_id)
        try:
            result = subprocess.run(
                [uvx, "--from", "semble[mcp]", "python", "-c",
                 f"from model2vec import StaticModel; StaticModel.from_pretrained('{model_id}'); print('ok')"],
                capture_output=True, text=True, timeout=300,
                env={**os.environ, "PATH": _wsl_path()},
            )
            if result.returncode == 0 and "ok" in result.stdout:
                return [PreflightResult(
                    name="Semble: potion-code-16M model",
                    passed=True,
                    level="info",
                    detail=f"Model '{model_id}' downloaded and ready",
                )]
            return [PreflightResult(
                name="Semble: potion-code-16M model",
                passed=False,
                level="warning",
                detail=f"Model download failed (exit {result.returncode}): {result.stderr.strip()[:200]}",
            )]
        except subprocess.TimeoutExpired:
            return [PreflightResult(
                name="Semble: potion-code-16M model",
                passed=False,
                level="warning",
                detail="Model download timed out after 300s — retry or check network connectivity",
            )]
        except Exception as exc:
            return [PreflightResult(
                name="Semble: potion-code-16M model",
                passed=False,
                level="warning",
                detail=f"Model download error: {exc}",
            )]


    def _check_fastembed_model(self) -> list[PreflightResult]:
        """Verify BAAI/bge-small-en-v1.5 is cached; download it if missing (needed for simple_rag)."""
        needs_simple_rag = any("simple_rag" in c.tools for c in self.configs)
        if not needs_simple_rag:
            return []

        model_id = "BAAI/bge-small-en-v1.5"
        hf_cache = os.path.expanduser("~/.cache/huggingface/hub")
        snap_base = os.path.join(hf_cache, "models--BAAI--bge-small-en-v1.5", "snapshots")

        if os.path.isdir(snap_base):
            for snap in os.listdir(snap_base):
                snap_dir = os.path.join(snap_base, snap)
                if os.path.isdir(snap_dir):
                    real_files = [f for f in os.listdir(snap_dir) if not f.startswith(".")]
                    if real_files:
                        return [PreflightResult(
                            name="SimpleRAG: bge-small-en-v1.5",
                            passed=True,
                            level="info",
                            detail=f"Model '{model_id}' cached ({len(real_files)} files)",
                        )]

        _log.info("Downloading fastembed model '%s'...", model_id)
        try:
            result = subprocess.run(
                [sys.executable, "-c",
                 f"from fastembed import TextEmbedding; TextEmbedding(model_name='{model_id}'); print('ok')"],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0 and "ok" in result.stdout:
                return [PreflightResult(
                    name="SimpleRAG: bge-small-en-v1.5",
                    passed=True,
                    level="info",
                    detail=f"Model '{model_id}' downloaded and ready",
                )]
            return [PreflightResult(
                name="SimpleRAG: bge-small-en-v1.5",
                passed=False,
                level="warning",
                detail=f"Download failed (exit {result.returncode}): {result.stderr.strip()[:200]}",
            )]
        except subprocess.TimeoutExpired:
            return [PreflightResult(
                name="SimpleRAG: bge-small-en-v1.5",
                passed=False,
                level="warning",
                detail="Model download timed out after 300s ? check network or pre-cache manually",
            )]
        except Exception as exc:
            return [PreflightResult(
                name="SimpleRAG: bge-small-en-v1.5",
                passed=False,
                level="warning",
                detail=f"Download error: {exc}",
            )]


    def _check_required_files(self) -> list[PreflightResult]:
        """Verify that required_files exist in the target repository."""
        if not self.required_files:
            return []
        results = []
        for rel_path in self.required_files:
            full_path = os.path.join(self.repo_path, rel_path)
            exists = os.path.isfile(full_path)
            results.append(PreflightResult(
                name=f"Required file: {rel_path}",
                passed=exists,
                level="warning",
                detail=full_path if exists else f"NOT FOUND in target repo: {full_path}",
            ))
        return results


class PreflightError(RuntimeError):
    """Raised when one or more critical pre-flight checks fail."""
