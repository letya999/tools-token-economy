import pytest
from src.core.models import RunMetrics
from src.core.scoring import compute_eval_composite, EPS

def test_net_spt_calculation():
    # Scenario 1: Gradual success (task_solved_score = 0.6)
    metrics = RunMetrics(
        success=True,
        eval_score=0.8,
        input_tokens=500,
        output_tokens=300,
        tool_tokens=200,
        duration_sec=10.0,
        model_calls=5,
        tool_calls=5,
        task_solved_score=0.6,
        schema_overhead_tokens=100
    )
    # total_tokens = 500 + 300 + 200 = 1000
    # reasoning_tokens = 1000 - 100 = 900
    # net_spt = (0.6 * 1000) / 900 = 600 / 900 = 0.666...
    assert metrics.total_tokens == 1000
    assert metrics.net_spt == pytest.approx(0.6666666666666666)

    # Scenario 2: Binary success fallback (task_solved_score = 0.0, success = True)
    metrics.task_solved_score = 0.0
    # net_spt = (1.0 * 1000) / 900 = 1.111...
    assert metrics.net_spt == pytest.approx(1.1111111111111112)

    # Scenario 3: Failure (success = False)
    metrics.success = False
    metrics.task_solved_score = 0.0
    # net_spt = (0.0 * 1000) / 900 = 0.0
    assert metrics.net_spt == 0.0

def test_compute_eval_composite_epsilon():
    weights = {"a": 0.5, "b": 0.5}
    
    # Scenario 1: One dimension is zero, should not be zero but heavily penalized
    scores = {"a": 0.0, "b": 1.0}
    # val_a = max(0.0, 0.01) = 0.01
    # val_b = max(1.0, 0.01) = 1.0
    # composite = (0.01^0.5) * (1.0^0.5) = 0.1 * 1.0 = 0.1
    result = compute_eval_composite(scores, weights, success=True)
    assert result == pytest.approx(0.1)

    # Scenario 2: Success is False, should be 0.0 regardless of scores
    result = compute_eval_composite(scores, weights, success=False)
    assert result == 0.0

    # Scenario 3: All dimensions positive
    scores = {"a": 1.0, "b": 1.0}
    result = compute_eval_composite(scores, weights, success=True)
    assert result == pytest.approx(1.0)
