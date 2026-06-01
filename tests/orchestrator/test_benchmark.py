import os
from unittest.mock import MagicMock, patch

import pytest

from src.core.models import (
    AgentConfig,
    CodebaseConfig,
    ProviderConfig,
    RunMetrics,
    TaskConfig,
)
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
def mock_provider_config() -> ProviderConfig:
    return ProviderConfig(model="mock-model", max_steps=10)


@pytest.fixture
def mock_tools_configs() -> list[AgentConfig]:
    return [
        AgentConfig(id="01_cursor_like", name="Cursor-like", archetype="cursor", tools=["read", "patch"], model="gemini-2.5-flash", max_steps=5),
        AgentConfig(id="02_grep", name="Grep", archetype="ablation", tools=["grep", "read", "patch"], model="gemini-2.5-flash", max_steps=5),
    ]


@pytest.fixture
def mock_task_config() -> TaskConfig:
    return TaskConfig(description="Fix the bug", test_cmd="pytest", timeout_sec=60, required_files=[])


@pytest.fixture
def mock_codebase_config(mock_repo) -> CodebaseConfig:
    return CodebaseConfig(local_path=mock_repo)


@pytest.fixture
def mock_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "dummy.py").write_text("x = 1\n")
    return str(repo)


@pytest.fixture
def orchestrator(mock_provider_config, mock_tools_configs, mock_task_config, mock_codebase_config, tmp_path):
    with patch("src.orchestrator.benchmark_runner.GitIsolationProvider"):
        orch = BenchmarkOrchestrator(
            provider_config=mock_provider_config,
            tools_configs=mock_tools_configs,
            task_config=mock_task_config,
            codebase_config=mock_codebase_config,
            weights_config={},
            results_dir=str(tmp_path / "results"),
            worktree_base=str(tmp_path / "worktrees"),
            dry_run=True,
        )
    return orch


def test_orchestrator_dry_run_runs_all_configs(orchestrator, tmp_path):
    """Dry-run mode goes through all configs and saves metrics files."""
    fake_wt = str(tmp_path / "wt")
    os.makedirs(fake_wt, exist_ok=True)

    orchestrator.isolation.setup = MagicMock(return_value=fake_wt)
    orchestrator.isolation.teardown = MagicMock()

    with patch.object(orchestrator, "_run_preflight"):
        orchestrator.run_suite()

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

    with patch.object(orchestrator, "_run_preflight"):
        orchestrator.run_suite()

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
    with patch.object(orchestrator, "_run_preflight"), \
         patch("src.orchestrator.benchmark_runner.AgnoRunner") as mock_runner_cls:
        mock_runner_cls.return_value.run = MagicMock(side_effect=RuntimeError("crash"))
        orchestrator.run_suite()

    # teardown must be called for each config despite errors
    assert orchestrator.isolation.teardown.call_count == 2


def test_get_tools_for_config_maps_correctly(orchestrator, tmp_path):
    fake_wt = str(tmp_path / "wt")
    config = AgentConfig(id="test", name="Test", archetype="test",
                         tools=["read", "grep", "lsp_symbols", "serena"], model="mock")
    tools = orchestrator._get_tools_for_config(config, fake_wt)
    tool_names = {t.name for t in tools}
    assert "read" in tool_names
    assert "grep" in tool_names
    assert "lsp_symbols" in tool_names
    # serena is an MCP tool — not in regular tools
    assert "serena" not in tool_names


def test_get_mcp_configs_for_config(orchestrator, tmp_path):
    config = AgentConfig(id="test", name="Test", archetype="test",
                         tools=["read", "grep", "serena", "semble"], model="mock")
    mcp_configs = orchestrator._get_mcp_configs_for_config(config)
    tool_names = {c.tool_name for c in mcp_configs}
    assert "serena" in tool_names
    assert "semble" in tool_names
    assert len(mcp_configs) == 2


def test_inject_serena_project_config_creates_file(orchestrator, tmp_path):
    fake_wt = str(tmp_path / "wt")
    os.makedirs(fake_wt, exist_ok=True)

    orchestrator._inject_serena_project_config(fake_wt)

    config_path = os.path.join(fake_wt, ".serena", "project.yml")
    assert os.path.isfile(config_path)
    import yaml
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    assert cfg["languages"] == ["python"]
    assert cfg["read_only"] is False


def test_inject_serena_project_config_idempotent(orchestrator, tmp_path):
    fake_wt = str(tmp_path / "wt")
    os.makedirs(fake_wt, exist_ok=True)

    orchestrator._inject_serena_project_config(fake_wt)
    config_path = os.path.join(fake_wt, ".serena", "project.yml")
    mtime_first = os.path.getmtime(config_path)

    orchestrator._inject_serena_project_config(fake_wt)
    assert os.path.getmtime(config_path) == mtime_first  # file not rewritten


def test_get_mcp_configs_empty_when_no_mcp_tools(orchestrator, tmp_path):
    config = AgentConfig(id="test", name="Test", archetype="test",
                         tools=["read", "grep", "rg"], model="mock")
    mcp_configs = orchestrator._get_mcp_configs_for_config(config)
    assert mcp_configs == []


def test_orchestrator_passes_test_cmd_to_runner(mock_provider_config, mock_tools_configs, mock_codebase_config, mock_repo, tmp_path):
    """Verify that test_cmd is passed down to AgnoRunner.run()."""
    
    custom_task_config = TaskConfig(description="task", test_cmd="uv run pytest --custom", timeout_sec=60, required_files=[])
    
    with patch("src.orchestrator.benchmark_runner.GitIsolationProvider"):
        orch = BenchmarkOrchestrator(
            provider_config=mock_provider_config,
            tools_configs=mock_tools_configs,
            task_config=custom_task_config,
            codebase_config=mock_codebase_config,
            weights_config={},
            results_dir=str(tmp_path / "results"),
            worktree_base=str(tmp_path / "worktrees"),
            dry_run=False
        )

    fake_wt = str(tmp_path / "wt")
    os.makedirs(fake_wt, exist_ok=True)
    orch.isolation.setup = MagicMock(return_value=fake_wt)
    orch.isolation.teardown = MagicMock()

    with patch.object(orch, "_run_preflight"), \
         patch.object(orch, "_setup_target_repo"), \
         patch.object(orch, "_capture_baseline", return_value=5), \
         patch("src.orchestrator.benchmark_runner.AgnoRunner") as mock_runner_cls:
        mock_runner = mock_runner_cls.return_value
        mock_runner.run = MagicMock(return_value=_mock_run_metrics())

        with patch.object(orch, "_get_tools_for_config", return_value=[]):
            orch.run_suite()

        # Verify runner.run was called with test_cmd
        _, called_kwargs = mock_runner.run.call_args
        assert called_kwargs["test_cmd"] == "uv run pytest --custom"
        assert called_kwargs.get("worktree_path") == fake_wt


