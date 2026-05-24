import os
from unittest.mock import MagicMock, patch

import pytest

from src.core.models import AgentConfig, RunMetrics
from src.features.evaluation import EvalOutcome
from src.orchestrator.benchmark import BenchmarkOrchestrator


def _mock_run_metrics(**overrides) -> RunMetrics:
    defaults = dict(
        success=True, eval_score=1.0,
        input_tokens=200, output_tokens=80, tool_tokens=40,
        duration_sec=3.0, model_calls=2, tool_calls=5,
    )
    defaults.update(overrides)
    return RunMetrics(**defaults)


@pytest.fixture
def minimal_configs_yaml(tmp_path):
    yaml_content = """
configs:
  - id: "01_cursor_like"
    name: "Cursor-like"
    archetype: "cursor"
    tools: ["read", "patch"]
    model: "gemini-2.5-flash"
    max_steps: 5
  - id: "02_grep"
    name: "Grep"
    archetype: "ablation"
    tools: ["grep", "read", "patch"]
    model: "gemini-2.5-flash"
    max_steps: 5
"""
    config_file = tmp_path / "configs.yaml"
    config_file.write_text(yaml_content)
    return str(config_file)


@pytest.fixture
def mock_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "dummy.py").write_text("x = 1\n")
    return str(repo)


@pytest.fixture
def orchestrator(minimal_configs_yaml, mock_repo, tmp_path):
    with patch("src.orchestrator.benchmark.GitIsolationProvider"):
        orch = BenchmarkOrchestrator(
            repo_path=mock_repo,
            configs_path=minimal_configs_yaml,
            results_dir=str(tmp_path / "results"),
            test_cmd="pytest",
            worktree_base=str(tmp_path / "worktrees"),
            dry_run=True,
        )
    return orch


def test_orchestrator_loads_configs(orchestrator):
    assert len(orchestrator.configs) == 2
    assert orchestrator.configs[0].id == "01_cursor_like"
    assert orchestrator.configs[1].id == "02_grep"


def test_orchestrator_dry_run_runs_all_configs(orchestrator, tmp_path):
    """Dry-run mode goes through all configs and saves metrics files."""
    fake_wt = str(tmp_path / "wt")
    os.makedirs(fake_wt, exist_ok=True)

    orchestrator.isolation.setup = MagicMock(return_value=fake_wt)
    orchestrator.isolation.teardown = MagicMock()
    orchestrator.eval_engine.evaluate = MagicMock(
        return_value=EvalOutcome(success=True, eval_score=1.0, output="1 passed",
                                 tests_passed=1, tests_failed=0, tests_total=1)
    )

    orchestrator.run_suite("Fix the bug")

    # One result dir per config
    results_base = str(tmp_path / "results")
    result_dirs = [d for d in os.listdir(results_base) if d.startswith("run_")]
    assert len(result_dirs) == 2
    for d in result_dirs:
        assert os.path.isfile(os.path.join(results_base, d, "metrics.json"))


def test_orchestrator_rankings_generated_after_suite(orchestrator, tmp_path):
    fake_wt = str(tmp_path / "wt")
    os.makedirs(fake_wt, exist_ok=True)

    orchestrator.isolation.setup = MagicMock(return_value=fake_wt)
    orchestrator.isolation.teardown = MagicMock()
    orchestrator.eval_engine.evaluate = MagicMock(
        return_value=EvalOutcome(success=True, eval_score=1.0, output="",
                                 tests_passed=0, tests_failed=0, tests_total=0)
    )

    orchestrator.run_suite("task")

    rankings_file = os.path.join(str(tmp_path / "results"), "RANKINGS.md")
    assert os.path.isfile(rankings_file)
    content = open(rankings_file).read()
    assert "Benchmark Rankings" in content
    assert "01_cursor_like" in content or "02_grep" in content


def test_orchestrator_teardown_called_on_error(orchestrator, tmp_path):
    """Teardown must happen even if the agent crashes."""
    fake_wt = str(tmp_path / "wt")
    os.makedirs(fake_wt, exist_ok=True)

    orchestrator.isolation.setup = MagicMock(return_value=fake_wt)
    orchestrator.isolation.teardown = MagicMock()
    # Simulate crash during agent run
    with patch("src.orchestrator.benchmark.AgnoRunner") as mock_runner_cls:
        mock_runner_cls.return_value.run = MagicMock(side_effect=RuntimeError("crash"))
        orchestrator.run_suite("task")

    # teardown must be called for each config despite errors
    assert orchestrator.isolation.teardown.call_count == 2


def test_get_tools_for_config_maps_correctly(orchestrator, tmp_path):
    fake_wt = str(tmp_path / "wt")
    config = AgentConfig(id="test", name="Test", archetype="test",
                         tools=["read", "grep", "lsp_symbols", "serena"])
    tools = orchestrator._get_tools_for_config(config, fake_wt)
    tool_names = {t.name for t in tools}
    assert "read" in tool_names
    assert "grep" in tool_names
    assert "lsp_symbols" in tool_names
    assert "serena" in tool_names


def test_eval_engine_tests_passed_merged_into_metrics(orchestrator, tmp_path):
    """tests_passed from EvalEngine should appear in saved metrics.json."""
    import json
    fake_wt = str(tmp_path / "wt")
    os.makedirs(fake_wt, exist_ok=True)

    orchestrator.isolation.setup = MagicMock(return_value=fake_wt)
    orchestrator.isolation.teardown = MagicMock()
    orchestrator.eval_engine.evaluate = MagicMock(
        return_value=EvalOutcome(success=True, eval_score=0.8, output="8 passed, 2 failed",
                                 tests_passed=8, tests_failed=2, tests_total=10)
    )

    orchestrator.run_suite("task")

    results_base = str(tmp_path / "results")
    metrics_files = []
    for d in os.listdir(results_base):
        mf = os.path.join(results_base, d, "metrics.json")
        if os.path.isfile(mf):
            metrics_files.append(mf)

    assert metrics_files
    data = json.loads(open(metrics_files[0]).read())
    assert data["tests_passed"] == 8
