import os
import json
import numpy as np
import time
from pathlib import Path
from typing import Any

NUMERIC_METRICS = [
    "eval_score",
    "input_tokens",
    "output_tokens",
    "tool_tokens",
    "duration_sec",
    "model_calls",
    "tool_calls",
    "tests_passed",
    "files_read",
    "files_changed",
    "patch_lines",
    "errors",
    "tool_errors",
    "task_solved_score",
    "tool_correctness_score",
    "correctness_score",
    "minimality_score",
    "pattern_adherence_score",
    "tool_sequence_score",
    "context_quality_score",
    "retrieval_precision",
    "retrieval_recall",
    "agent_cycles",
    "time_to_target",
    "context_waste_ratio",
    "warmup_sec",
    "total_tokens",
    "avg_tokens_per_tool",
    "cost_usd",
    "success_per_token"
]

def write_session_meta(results_dir: str, session_id: str, meta_dict: dict[str, Any]):
    """Writes results/session_{session_id}_meta.json."""
    path = Path(results_dir) / f"session_{session_id}_meta.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta_dict, f, indent=2)

def list_sessions(results_dir: str) -> list[dict[str, Any]]:
    """
    Scans results/ for session_*_meta.json files.
    Also returns "single" pseudo-sessions for un-sessionized run_* folders.
    """
    results_path = Path(results_dir)
    if not results_path.exists():
        return []

    sessions = []
    
    # 1. Load explicit sessions
    for meta_file in results_path.glob("session_*_meta.json"):
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
                session_id = meta_file.name.replace("session_", "").replace("_meta.json", "")
                meta["session_id"] = session_id
                sessions.append(meta)
        except Exception:
            continue

    # 2. Add single runs as pseudo-sessions
    for run_dir in results_path.glob("run_*"):
        if not run_dir.is_dir():
            continue
        
        # Check if it's a multi-run session run (run_{session_id}_r{rep}_{config_id})
        folder_name = run_dir.name
        parts = folder_name.split("_")
        is_multi = False
        if len(parts) >= 4:
            # Check if any part matches r[0-9]{3}
            for p in parts:
                if p.startswith("r") and len(p) == 4 and p[1:].isdigit():
                    is_multi = True
                    break
        
        if is_multi:
            continue
            
        # If it's a single run, add it as a pseudo-session if not already processed
        # run_20260526_123456_01_config -> session_id = 20260526_123456
        if len(parts) >= 3:
            session_id = f"{parts[1]}_{parts[2]}"
        else:
            session_id = folder_name.replace("run_", "")
        
        if not any(s["session_id"] == session_id for s in sessions):
            sessions.append({
                "session_id": session_id,
                "n_runs": 1,
                "n_completed": 1,
                "is_pseudo": True,
                "start_time": session_id
            })

    return sorted(sessions, key=lambda x: x.get("start_time", ""), reverse=True)

def aggregate_session(results_dir: str, session_id: str, percentile: int = 75) -> dict[str, dict[str, Any]]:
    """
    Finds all folders matching run_{session_id}_*
    Groups by config_id and computes aggregates.
    """
    results_path = Path(results_dir)
    config_data = {}

    # Find all runs for this session
    search_pattern = f"run_{session_id}_*"
    for run_dir in results_path.glob(search_pattern):
        metrics_file = run_dir / "metrics.json"
        if not metrics_file.exists():
            continue
            
        folder_name = run_dir.name
        parts = folder_name.split("_")
        
        # Determine config_id
        # run_{session_id}_r{rep}_{config_id}
        # or run_{session_id}_{config_id}
        rep_idx = -1
        for i, p in enumerate(parts):
            if p.startswith("r") and len(p) == 4 and p[1:].isdigit():
                rep_idx = i
                break
        
        if rep_idx != -1:
            config_id = "_".join(parts[rep_idx+1:])
        else:
            config_id = "_".join(parts[3:]) if len(parts) >= 4 else parts[-1]
        
        # Load metrics
        try:
            with open(metrics_file, "r", encoding="utf-8") as f:
                metrics = json.load(f)
        except Exception:
            continue
            
        if config_id not in config_data:
            config_data[config_id] = {m: [] for m in NUMERIC_METRICS}
            config_data[config_id]["success"] = []
            
        for m in NUMERIC_METRICS:
            if m in metrics:
                config_data[config_id][m].append(metrics[m])
        
        if "success" in metrics:
            config_data[config_id]["success"].append(1 if metrics["success"] else 0)

    aggregated = {}
    for config_id, data in config_data.items():
        stats = {}
        n = len(data["success"])
        if n == 0:
            continue
            
        stats["metadata"] = {"n": n}
        
        # Success rate
        success_rate = sum(data["success"]) / n
        stats["success"] = success_rate > 0.5
        stats["success_rate"] = success_rate
        
        for m in NUMERIC_METRICS:
            vals = data[m]
            if not vals:
                stats[m] = 0.0
                continue
                
            stats[m] = float(np.percentile(vals, percentile))
            stats["metadata"][m] = {
                "n": n,
                "p25": float(np.percentile(vals, 25)),
                "p50": float(np.percentile(vals, 50)),
                "p75": float(np.percentile(vals, 75)),
                "mean": float(np.mean(vals)),
                "std": float(np.std(vals))
            }
            
        aggregated[config_id] = stats
        
    return aggregated
