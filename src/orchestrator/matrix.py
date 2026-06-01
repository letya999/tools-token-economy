import json
import logging
import os
import time
from datetime import datetime
from typing import Any

from src.core.models import CodebaseConfig, ProviderConfig, TaskConfig, AgentConfig
from src.orchestrator.benchmark import BenchmarkOrchestrator

_log = logging.getLogger(__name__)

class MatrixOrchestrator:
    """
    Orchestrates a models × tasks matrix run.
    """

    def __init__(
        self,
        models: list[ProviderConfig],
        tasks: list[TaskConfig],
        agent_configs: list[AgentConfig],
        codebase: CodebaseConfig,
        weights: dict[str, Any],
        results_dir: str = "results",
        n_runs: int = 5,
        dry_run: bool = False,
        max_matrix_usd: float = 50.0,
    ):
        self.models = models
        self.tasks = tasks
        self.agent_configs = agent_configs
        self.codebase = codebase
        self.weights = weights
        self.results_dir = results_dir
        self.n_runs = n_runs
        self.dry_run = dry_run
        self.max_matrix_usd = max_matrix_usd
        self.matrix_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.manifest_path = os.path.join(results_dir, f"matrix_{self.matrix_timestamp}_manifest.json")
        self.cumulative_cost = 0.0

    def run(self):
        """Execute the matrix cell-by-cell."""
        manifest = {
            "timestamp": self.matrix_timestamp,
            "models": [m.model for m in self.models],
            "tasks": [t.name for t in self.tasks],
            "n_runs": self.n_runs,
            "cells": []
        }
        
        _log.info("Starting Matrix Run: %d models × %d tasks", len(self.models), len(self.tasks))
        
        # Iterate Model (Outer), Task (Inner)
        for model_cfg in self.models:
            model_slug = model_cfg.model.replace("/", "_").replace(".", "_")
            
            for task_cfg in self.tasks:
                task_slug = task_cfg.name.replace(" ", "_").lower()
                session_id = f"matrix_{self.matrix_timestamp}_{model_slug}_{task_slug}"
                
                cell_info = {
                    "model": model_cfg.model,
                    "task": task_cfg.name,
                    "session_id": session_id,
                    "status": "pending",
                    "cost_usd": 0.0
                }
                manifest["cells"].append(cell_info)
                self._save_manifest(manifest)

                if self.cumulative_cost >= self.max_matrix_usd and not self.dry_run:
                    _log.warning("Matrix budget exceeded ($%.2f >= $%.2f). Skipping cell %s.", 
                                 self.cumulative_cost, self.max_matrix_usd, session_id)
                    cell_info["status"] = "skipped_budget"
                    continue

                _log.info("--- Executing Matrix Cell: Model=%s, Task=%s ---", model_cfg.model, task_cfg.name)
                
                try:
                    orchestrator = BenchmarkOrchestrator(
                        provider_config=model_cfg,
                        tools_configs=self.agent_configs,
                        task_config=task_cfg,
                        codebase_config=self.codebase,
                        weights_config=self.weights,
                        results_dir=self.results_dir,
                        n_runs=self.n_runs,
                        dry_run=self.dry_run,
                    )
                    
                    # Run the suite for this cell
                    results = orchestrator.run_suite(session_id=session_id)
                    
                    # Update metrics
                    cell_cost = sum(r.metrics.cost_usd for r in results if r.metrics)
                    self.cumulative_cost += cell_cost
                    cell_info["status"] = "completed"
                    cell_info["cost_usd"] = cell_cost
                    
                except Exception as e:
                    _log.exception("Matrix cell %s failed", session_id)
                    cell_info["status"] = f"failed: {str(e)}"
                
                self._save_manifest(manifest)
                
        _log.info("Matrix Run Complete. Total Cost: $%.4f", self.cumulative_cost)
        return manifest

    def _save_manifest(self, manifest: dict):
        os.makedirs(os.path.dirname(self.manifest_path), exist_ok=True)
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
