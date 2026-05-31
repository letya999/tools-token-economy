import os
import yaml
from typing import Any

_DEFAULT_EVAL_WEIGHTS: dict[str, float] = {
    "task_solved_score":       0.35,
    "correctness_score":       0.20,
    "context_quality_score":   0.15,
    "minimality_score":        0.10,
    "tool_correctness_score":  0.10,
    "pattern_adherence_score": 0.05,
    "tool_sequence_score":     0.05,
}

def get_weights_config_path() -> str:
    """Return the absolute path to the benchmark weights config."""
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "configs", "benchmark_weights.yaml"
    )

def eval_weights() -> dict[str, float]:
    """Load evaluation weights from configs/benchmark_weights.yaml or return defaults."""
    path = get_weights_config_path()
    if not os.path.exists(path):
        return _DEFAULT_EVAL_WEIGHTS
    try:
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        return cfg.get("eval_weights", _DEFAULT_EVAL_WEIGHTS)
    except Exception:
        return _DEFAULT_EVAL_WEIGHTS

def compute_eval_composite(judge_scores: dict[str, Any], weights: dict[str, float], success: bool) -> float:
    """
    Weighted geometric mean of judge dimensions.
    Returns 0.0 if not success (success is a hard gate).
    Otherwise returns weighted geometric mean (weights must sum to 1.0).
    """
    if not success or not weights:
        return 0.0
    
    product = 1.0
    for key, w in weights.items():
        # Handle scores being passed as strings or numbers
        val = judge_scores.get(key, 0.0)
        try:
            val = float(val)
        except (ValueError, TypeError):
            val = 0.0
            
        if val <= 0.0:
            # Geometric mean becomes 0 if any contributing score is 0
            return 0.0
        product *= val ** w
    
    return float(product)
