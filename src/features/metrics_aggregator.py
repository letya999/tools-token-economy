import os
import json
import yaml
from datetime import datetime
from typing import Any, Dict
from src.core.models import EvalResult

class MetricsAggregator:
    """
    Saves and aggregates results of benchmark runs.
    """
    def __init__(self, results_base_dir: str):
        self.results_base_dir = os.path.abspath(results_base_dir)
        os.makedirs(self.results_base_dir, exist_ok=True)

    def save_run(self, result: EvalResult) -> str:
        """
        Saves run artifacts to a dedicated folder.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir_name = f"run_{timestamp}_{result.config_id}"
        run_dir = os.path.join(self.results_base_dir, run_dir_name)
        os.makedirs(run_dir, exist_ok=True)

        # Save metrics as JSON
        metrics_path = os.path.join(run_dir, "metrics.json")
        with open(metrics_path, "w", encoding="utf-8") as f:
            f.write(result.metrics.model_dump_json(indent=2))

        # Save patch if present
        if result.patch:
            patch_path = os.path.join(run_dir, "final.patch")
            with open(patch_path, "w", encoding="utf-8") as f:
                f.write(result.patch)

        # Save errors if present
        if result.error:
            error_path = os.path.join(run_dir, "error.log")
            with open(error_path, "w", encoding="utf-8") as f:
                f.write(result.error)

        return run_dir
