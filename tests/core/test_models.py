from src.core.models import AgentConfig, BenchmarkMeta, RunMetrics


def test_benchmark_meta_defaults():
    meta = BenchmarkMeta(repo="myrepo", task="fix bug")
    assert meta.max_iterations == 15
    assert meta.max_cost_usd_suite == 5.0
    assert meta.max_tokens_per_config == 500_000


def test_benchmark_meta_custom_iterations():
    meta = BenchmarkMeta(repo="myrepo", task="fix bug", max_iterations=8)
    assert meta.max_iterations == 8


def test_agent_config_validation():
    config = AgentConfig(
        id="01_cursor",
        name="Cursor Like",
        archetype="cursor",
        tools=["read", "patch", "repo_map"]
    )
    assert config.id == "01_cursor"
    assert "read" in config.tools

def test_run_metrics_calculation():
    metrics = RunMetrics(
        success=True,
        eval_score=1.0,
        input_tokens=1000,
        output_tokens=500,
        tool_tokens=200,
        duration_sec=120.5,
        model_calls=5,
        tool_calls=10
    )
    assert metrics.total_tokens == 1700
    # Assuming cost calculation is part of the model
    assert metrics.cost_usd > 0

from src.core.models import (
    ProviderConfig, TaskConfig, CodebaseConfig, McpServerConfig, RunMetrics
)
from dataclasses import field


def test_provider_config_defaults():
    cfg = ProviderConfig()
    assert cfg.provider == "openai"
    assert cfg.model == "gpt-4.1-mini"
    assert cfg.max_steps == 50
    assert cfg.temperature == 0.0


def test_task_config_defaults():
    cfg = TaskConfig()
    assert cfg.difficulty == "medium"
    assert cfg.required_files == []
    assert cfg.target_file is None


def test_codebase_config_defaults():
    cfg = CodebaseConfig()
    assert cfg.local_path == ""
    assert cfg.branch == "main"


def test_mcp_server_config_warmup_fields():
    cfg = McpServerConfig(
        tool_name="serena",
        command="serena",
        args_template=["start-mcp-server", "--project", "{path}"],
        warmup_call="get_symbols_overview",
        warmup_args={"project": "/tmp"},
    )
    assert cfg.warmup_call == "get_symbols_overview"
    assert cfg.warmup_args == {"project": "/tmp"}
    # Default is None/empty
    cfg2 = McpServerConfig(tool_name="t", command="t", args_template=[])
    assert cfg2.warmup_call is None
    assert cfg2.warmup_args == {}


def test_run_metrics_new_fields_defaults():
    m = RunMetrics(
        success=True, eval_score=1.0,
        input_tokens=100, output_tokens=50, tool_tokens=30,
        duration_sec=5.0, model_calls=2, tool_calls=5,
    )
    assert m.agent_cycles == 0
    assert m.time_to_target == 0
    assert m.context_waste_ratio == 0.0
    assert m.warmup_sec == 0.0


def test_run_metrics_avg_tokens_per_tool_computed():
    # tool_calls=5, tool_tokens=100 ? avg=20.0
    m = RunMetrics(
        success=True, eval_score=1.0,
        input_tokens=100, output_tokens=50, tool_tokens=100,
        duration_sec=5.0, model_calls=2, tool_calls=5,
    )
    assert m.avg_tokens_per_tool == 20.0


def test_run_metrics_avg_tokens_per_tool_zero_division():
    # tool_calls=0 ? avg=0.0 (no division by zero)
    m = RunMetrics(
        success=False, eval_score=0.0,
        input_tokens=0, output_tokens=0, tool_tokens=0,
        duration_sec=1.0, model_calls=0, tool_calls=0,
    )
    assert m.avg_tokens_per_tool == 0.0


def test_run_metrics_all_new_fields_serialized():
    """New fields must appear in model_dump() so metrics.json captures them."""
    m = RunMetrics(
        success=True, eval_score=1.0,
        input_tokens=100, output_tokens=50, tool_tokens=80,
        duration_sec=5.0, model_calls=2, tool_calls=4,
        agent_cycles=3, time_to_target=2, context_waste_ratio=0.4, warmup_sec=1.5,
    )
    d = m.model_dump()
    assert d["agent_cycles"] == 3
    assert d["time_to_target"] == 2
    assert d["context_waste_ratio"] == 0.4
    assert d["warmup_sec"] == 1.5
    assert "avg_tokens_per_tool" in d   # computed field must be serialized
    assert d["avg_tokens_per_tool"] == 20.0
