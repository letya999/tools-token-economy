import os
import shutil
import subprocess
from unittest.mock import patch

import pytest

from src.core.models import AgentConfig
from src.features.preflight import PreflightChecker, PreflightError, PreflightReport, PreflightResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(tool_names: list[str], model: str = "openai/gpt-4.1-mini") -> AgentConfig:
    return AgentConfig(id="test", name="Test", archetype="test", tools=tool_names, model=model)


@pytest.fixture
def git_repo(tmp_path):
    """Minimal git repo for target-repo checks."""
    git = shutil.which("git") or "git"
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run([git, "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run([git, "config", "user.email", "t@t.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run([git, "config", "user.name", "T"], cwd=repo, check=True, capture_output=True)
    (repo / "placeholder.txt").write_text("x")
    subprocess.run([git, "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run([git, "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    return repo


# ---------------------------------------------------------------------------
# PreflightReport
# ---------------------------------------------------------------------------

class TestPreflightReport:
    def test_all_critical_passed_when_no_failures(self):
        report = PreflightReport()
        report.add(PreflightResult("A", passed=True, level="critical"))
        report.add(PreflightResult("B", passed=True, level="warning"))
        assert report.all_critical_passed

    def test_all_critical_passed_false_on_critical_failure(self):
        report = PreflightReport()
        report.add(PreflightResult("A", passed=False, level="critical"))
        assert not report.all_critical_passed

    def test_warning_failure_does_not_block(self):
        report = PreflightReport()
        report.add(PreflightResult("A", passed=True, level="critical"))
        report.add(PreflightResult("B", passed=False, level="warning"))
        assert report.all_critical_passed


# ---------------------------------------------------------------------------
# CLI tool checks
# ---------------------------------------------------------------------------

class TestPythonPackageChecks:
    def test_tree_sitter_python_checked_when_tree_sitter_tool_used(self, git_repo):
        checker = PreflightChecker(
            repo_path=str(git_repo),
            configs=[_make_config(["tree_sitter"])],
            test_cmd="pytest",
        )
        results = checker._check_python_packages()
        names = [r.name for r in results]
        assert "Python package: tree_sitter_python" in names

    def test_tree_sitter_python_is_critical_when_needed(self, git_repo):
        checker = PreflightChecker(
            repo_path=str(git_repo),
            configs=[_make_config(["tree_sitter"])],
            test_cmd="pytest",
        )
        import unittest.mock as _mock
        import importlib.util as _ilu
        original = _ilu.find_spec

        def _find_spec_stub(name):
            if name == "tree_sitter_python":
                return None
            return original(name)

        with _mock.patch("importlib.util.find_spec", side_effect=_find_spec_stub):
            results = checker._check_python_packages()

        ts_py = next(r for r in results if r.name == "Python package: tree_sitter_python")
        assert ts_py.level == "critical"
        assert not ts_py.passed

    def test_tree_sitter_python_is_warning_for_unrelated_tools(self, git_repo):
        checker = PreflightChecker(
            repo_path=str(git_repo),
            configs=[_make_config(["rg", "grep"])],
            test_cmd="pytest",
        )
        results = checker._check_python_packages()
        ts_py = next((r for r in results if r.name == "Python package: tree_sitter_python"), None)
        # Package is always checked, but only critical when tree_sitter tool is active
        assert ts_py is not None
        assert ts_py.level == "warning"


class TestToolCliDeps:
    def test_pure_python_tools_need_no_cli(self, git_repo):
        checker = PreflightChecker(
            repo_path=str(git_repo),
            configs=[_make_config(["read", "write", "patch", "glob", "tree_sitter"])],
            test_cmd="pytest",
            dry_run=False,
        )
        results = checker._check_tool_cli_deps()
        # No CLI requirements for these tools
        assert results == []

    def test_rg_tool_requires_rg_binary(self, git_repo):
        checker = PreflightChecker(
            repo_path=str(git_repo),
            configs=[_make_config(["rg"])],
            test_cmd="pytest",
        )
        results = checker._check_tool_cli_deps()
        assert any(r.name == "CLI tool: rg" for r in results)

    def test_missing_binary_is_critical_failure(self, git_repo):
        checker = PreflightChecker(
            repo_path=str(git_repo),
            configs=[_make_config(["ugrep"])],
            test_cmd="pytest",
        )
        with patch("shutil.which", return_value=None):
            results = checker._check_tool_cli_deps()

        ugrep_result = next(r for r in results if "ugrep" in r.name)
        assert ugrep_result.level == "critical"
        assert not ugrep_result.passed

    def test_git_not_duplicated_in_cli_check(self, git_repo):
        checker = PreflightChecker(
            repo_path=str(git_repo),
            configs=[_make_config(["git_grep"])],
            test_cmd="pytest",
        )
        results = checker._check_tool_cli_deps()
        # git_grep needs "git" but git is already checked separately
        assert not any(r.name == "CLI tool: git" for r in results)


# ---------------------------------------------------------------------------
# API key checks
# ---------------------------------------------------------------------------

class TestApiKeyChecks:
    def test_missing_openai_key_is_critical(self, git_repo):
        checker = PreflightChecker(
            repo_path=str(git_repo),
            configs=[_make_config([], model="openai/gpt-4.1-mini")],
            test_cmd="pytest",
        )
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            results = checker._check_api_keys()

        openai_result = next(r for r in results if "OPENAI_API_KEY" in r.name)
        assert openai_result.level == "critical"
        assert not openai_result.passed

    def test_present_openai_key_passes(self, git_repo):
        checker = PreflightChecker(
            repo_path=str(git_repo),
            configs=[_make_config([], model="openai/gpt-4.1-mini")],
            test_cmd="pytest",
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            results = checker._check_api_keys()

        openai_result = next(r for r in results if "OPENAI_API_KEY" in r.name)
        assert openai_result.passed

    def test_gemini_accepts_either_key(self, git_repo):
        checker = PreflightChecker(
            repo_path=str(git_repo),
            configs=[_make_config([], model="gemini-2.5-flash")],
            test_cmd="pytest",
        )
        env = {k: v for k, v in os.environ.items()
               if k not in ("GOOGLE_API_KEY", "GEMINI_API_KEY")}
        with patch.dict(os.environ, {**env, "GEMINI_API_KEY": "gm-test"}, clear=True):
            results = checker._check_api_keys()

        key_result = next((r for r in results if "GOOGLE_API_KEY" in r.name), None)
        if key_result:
            assert key_result.passed


# ---------------------------------------------------------------------------
# Target repo checks
# ---------------------------------------------------------------------------

class TestTargetRepoChecks:
    def test_missing_repo_is_critical(self, tmp_path):
        checker = PreflightChecker(
            repo_path=str(tmp_path / "nonexistent"),
            configs=[_make_config([])],
            test_cmd="pytest",
        )
        results = checker._check_target_repo()
        assert any(not r.passed and r.level == "critical" for r in results)

    def test_valid_git_repo_passes(self, git_repo):
        checker = PreflightChecker(
            repo_path=str(git_repo),
            configs=[_make_config([])],
            test_cmd="pytest",
        )
        results = checker._check_target_repo()
        assert all(r.passed for r in results)

    def test_non_git_dir_fails_git_check(self, tmp_path):
        (tmp_path / "somefile.py").write_text("x")
        checker = PreflightChecker(
            repo_path=str(tmp_path),
            configs=[_make_config([])],
            test_cmd="pytest",
        )
        results = checker._check_target_repo()
        git_result = next(r for r in results if "is git" in r.name)
        assert not git_result.passed
        assert git_result.level == "critical"


# ---------------------------------------------------------------------------
# selected_ids filtering
# ---------------------------------------------------------------------------

class TestSelectedIds:
    def test_only_selected_configs_checked(self, git_repo):
        configs = [
            _make_config(["rg"], model="openai/gpt-4.1-mini"),   # id="test"
            AgentConfig(id="other", name="Other", archetype="x", tools=["ugrep"], model="openai/gpt-4.1-mini"),
        ]
        configs[0] = AgentConfig(id="rg_config", name="RG", archetype="x", tools=["rg"], model="openai/gpt-4.1-mini")
        configs[1] = AgentConfig(id="ug_config", name="UG", archetype="x", tools=["ugrep"], model="openai/gpt-4.1-mini")

        checker = PreflightChecker(
            repo_path=str(git_repo),
            configs=configs,
            test_cmd="pytest",
            selected_ids=["rg_config"],
        )
        # Only rg_config selected — checker should only have that config
        assert len(checker.configs) == 1
        assert checker.configs[0].id == "rg_config"


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

class TestDryRun:
    def test_dry_run_flag_is_stored(self, git_repo):
        checker = PreflightChecker(
            repo_path=str(git_repo),
            configs=[_make_config([])],
            test_cmd="pytest",
            dry_run=True,
        )
        assert checker.dry_run is True

    def test_dry_run_does_not_skip_preflight(self, git_repo):
        checker = PreflightChecker(
            repo_path=str(git_repo),
            configs=[_make_config([], model="openai/gpt-4.1-mini")],
            test_cmd="pytest",
            dry_run=True,
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            report = checker.run()
        # With valid repo + API key, all critical checks should pass
        assert report.all_critical_passed


# ---------------------------------------------------------------------------
# Integration: raises PreflightError on critical failure
# ---------------------------------------------------------------------------

class TestPreflightError:
    def test_raises_on_missing_repo(self, tmp_path):
        checker = PreflightChecker(
            repo_path=str(tmp_path / "missing"),
            configs=[_make_config([], model="openai/gpt-4.1-mini")],
            test_cmd="pytest",
            dry_run=False,
        )
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            with patch("shutil.which", side_effect=lambda cmd: cmd if cmd != "git" else "git"):
                with pytest.raises(PreflightError):
                    checker.run()
