import pytest
import json
import os
from src.features.metrics_aggregator import MetricsAggregator
from src.core.models import EvalResult, RunMetrics


def _make_metrics(**overrides) -> RunMetrics:
    defaults = dict(
        success=True, eval_score=1.0,
        input_tokens=100, output_tokens=50, tool_tokens=20,
        duration_sec=5.0, model_calls=3, tool_calls=7,
    )
    defaults.update(overrides)
    return RunMetrics(**defaults)


def _make_result(run_id: str, config_id: str, **metric_overrides) -> EvalResult:
    return EvalResult(
        run_id=run_id,
        config_id=config_id,
        metrics=_make_metrics(**metric_overrides),
        success=metric_overrides.get("success", True),
    )


def test_save_run_creates_metrics_file(tmp_path):
    agg = MetricsAggregator(str(tmp_path))
    result = _make_result("run_001_cursor", "01_cursor_like")
    save_dir = agg.save_run(result)

    metrics_file = os.path.join(save_dir, "metrics.json")
    assert os.path.isfile(metrics_file)
    data = json.loads(open(metrics_file).read())
    assert data["success"] is True
    assert data["total_tokens"] == 170  # 100+50+20
    assert data["model_calls"] == 3


def test_save_run_computes_success_per_token(tmp_path):
    agg = MetricsAggregator(str(tmp_path))
    result = _make_result("run_002", "07_grep", success=True,
                          input_tokens=1000, output_tokens=0, tool_tokens=0)
    save_dir = agg.save_run(result)
    data = json.loads(open(os.path.join(save_dir, "metrics.json")).read())
    assert data["success_per_token"] == pytest.approx(1.0 / 1000)


def test_save_run_zero_token_success_per_token(tmp_path):
    agg = MetricsAggregator(str(tmp_path))
    result = _make_result("run_003", "05_read_only", success=False,
                          input_tokens=0, output_tokens=0, tool_tokens=0)
    save_dir = agg.save_run(result)
    data = json.loads(open(os.path.join(save_dir, "metrics.json")).read())
    assert data["success_per_token"] == 0.0


def test_save_run_writes_patch(tmp_path):
    agg = MetricsAggregator(str(tmp_path))
    result = _make_result("run_004", "09_rg")
    result = result.model_copy(update={"patch": "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new"})
    save_dir = agg.save_run(result)
    assert os.path.isfile(os.path.join(save_dir, "final.patch"))


def test_save_run_writes_error_log(tmp_path):
    agg = MetricsAggregator(str(tmp_path))
    result = _make_result("run_005", "13_lsp", success=False)
    result = result.model_copy(update={"error": "subprocess timed out"})
    save_dir = agg.save_run(result)
    assert os.path.isfile(os.path.join(save_dir, "error.log"))


def test_generate_rankings_sorted_by_success_per_token(tmp_path):
    agg = MetricsAggregator(str(tmp_path))

    # High-token success: low score
    agg.save_run(_make_result("run_high_token_01_cursor", "01_cursor",
                              success=True, input_tokens=10000, output_tokens=0, tool_tokens=0))
    # Low-token success: high score
    agg.save_run(_make_result("run_low_token_09_rg", "09_rg",
                              success=True, input_tokens=100, output_tokens=0, tool_tokens=0))
    # Failure: score is 0
    agg.save_run(_make_result("run_fail_05_read", "05_read",
                              success=False, input_tokens=500, output_tokens=0, tool_tokens=0))

    rankings = agg.generate_rankings()

    # Rankings file written
    assert os.path.isfile(os.path.join(str(tmp_path), "RANKINGS.md"))
    # Low-token success first
    lines = [l for l in rankings.splitlines() if "| " in l and "Run" not in l and "---" not in l]
    assert "run_low_token" in lines[0]
    # Failure last
    assert "run_fail" in lines[-1]


def test_generate_rankings_no_results(tmp_path):
    agg = MetricsAggregator(str(tmp_path))
    result = agg.generate_rankings()
    assert "No results" in result
