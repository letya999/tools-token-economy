import json
import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pytest

from src.features.multi_run import aggregate_session, list_sessions, write_session_meta


@pytest.fixture
def temp_results_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def test_write_session_meta(temp_results_dir):
    session_id = "20260528_120000"
    meta = {"n_runs": 10, "status": "running"}
    write_session_meta(temp_results_dir, session_id, meta)
    
    meta_path = Path(temp_results_dir) / f"session_{session_id}_meta.json"
    assert meta_path.exists()
    with open(meta_path, "r", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == meta


def test_list_sessions_empty(temp_results_dir):
    sessions = list_sessions(temp_results_dir)
    assert sessions == []


def test_list_sessions_with_meta(temp_results_dir):
    session_id = "20260528_120000"
    meta = {"n_runs": 10, "start_time": "20260528_120000"}
    write_session_meta(temp_results_dir, session_id, meta)
    
    sessions = list_sessions(temp_results_dir)
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == session_id
    assert sessions[0]["n_runs"] == 10


def test_aggregate_session_single_rep(temp_results_dir):
    session_id = "20260528_120000"
    config_id = "01_baseline"
    run_id = f"run_{session_id}_r001_{config_id}"
    run_dir = Path(temp_results_dir) / run_id
    run_dir.mkdir()
    
    metrics = {
        "success": True,
        "eval_score": 0.8,
        "total_tokens": 1000,
        "success_per_token": 800.0,
        "duration_sec": 10.0,
        "model_calls": 5,
        "tool_calls": 10
    }
    with open(run_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f)
        
    agg = aggregate_session(temp_results_dir, session_id)
    assert config_id in agg
    assert agg[config_id]["eval_score"] == 0.8
    assert agg[config_id]["total_tokens"] == 1000
    assert agg[config_id]["metadata"]["n"] == 1


def test_aggregate_session_p75(temp_results_dir):
    session_id = "20260528_120000"
    config_id = "01_baseline"
    
    # 4 reps with eval_scores: 0.2, 0.4, 0.6, 0.8
    # p75 of [0.2, 0.4, 0.6, 0.8] is 0.65 (numpy uses interpolation by default)
    # Actually np.percentile([0.2, 0.4, 0.6, 0.8], 75) = 0.65
    scores = [0.2, 0.4, 0.6, 0.8]
    for i, score in enumerate(scores, 1):
        run_id = f"run_{session_id}_r{i:03d}_{config_id}"
        run_dir = Path(temp_results_dir) / run_id
        run_dir.mkdir()
        with open(run_dir / "metrics.json", "w", encoding="utf-8") as f:
            json.dump({"success": True, "eval_score": score}, f)
            
    agg = aggregate_session(temp_results_dir, session_id, percentile=75)
    assert config_id in agg
    expected_p75 = float(np.percentile(scores, 75))
    assert agg[config_id]["eval_score"] == pytest.approx(expected_p75)
    assert agg[config_id]["metadata"]["n"] == 4


def test_aggregate_session_partial(temp_results_dir):
    session_id = "20260528_120000"
    config_id = "01_baseline"
    
    # 3 of 4 reps exist
    scores = [0.4, 0.6, 0.8]
    for i, score in enumerate(scores, 1):
        run_id = f"run_{session_id}_r{i:03d}_{config_id}"
        run_dir = Path(temp_results_dir) / run_id
        run_dir.mkdir()
        with open(run_dir / "metrics.json", "w", encoding="utf-8") as f:
            json.dump({"success": True, "eval_score": score}, f)
            
    agg = aggregate_session(temp_results_dir, session_id)
    assert config_id in agg
    assert agg[config_id]["metadata"]["n"] == 3
