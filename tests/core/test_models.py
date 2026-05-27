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
