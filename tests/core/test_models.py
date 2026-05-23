from src.core.models import AgentConfig, RunMetrics


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
