import glob as glob_module
import json
import os

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
        # run_id already contains timestamp and config_id
        run_dir = os.path.join(self.results_base_dir, result.run_id)
        os.makedirs(run_dir, exist_ok=True)

        # Save metrics as JSON
        metrics_path = os.path.join(run_dir, "metrics.json")
        with open(metrics_path, "w", encoding="utf-8") as f:
            # Use model_dump to get a dict, then add success field explicitly if model_dump_json misses it
            # Actually success_per_token is a computed field, model_dump_json should include it in Pydantic v2
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

    def generate_rankings(self) -> str:
        """
        Reads all metrics.json files from results directory and generates
        a markdown rankings table sorted by success_per_token descending.
        """
        rows = []
        for metrics_file in glob_module.glob(os.path.join(self.results_base_dir, "run_*", "metrics.json")):
            run_dir = os.path.dirname(metrics_file)
            run_name = os.path.basename(run_dir)
            try:
                with open(metrics_file, encoding="utf-8") as f:
                    data = json.load(f)
                rows.append({
                    "run": run_name,
                    "success": data.get("success", False),
                    "total_tokens": data.get("total_tokens", 0),
                    "success_per_token": data.get("success_per_token", 0.0),
                    "duration_sec": round(data.get("duration_sec", 0.0), 2),
                    "model_calls": data.get("model_calls", 0),
                    "tool_calls": data.get("tool_calls", 0),
                    "cost_usd": round(data.get("cost_usd", 0.0), 6),
                })
            except Exception:
                continue

        if not rows:
            return "No results found to rank."

        # Sort by success_per_token desc, then total_tokens asc
        rows.sort(key=lambda r: (-r["success_per_token"], r["total_tokens"]))

        lines = [
            "# Benchmark Rankings",
            "",
            "| # | Run | Success | Total Tokens | Success/Token | Duration(s) | Model Calls | Tool Calls | Cost USD |",
            "|---|-----|---------|-------------|---------------|-------------|-------------|------------|----------|",
        ]
        for i, r in enumerate(rows, 1):
            ok = "✓" if r["success"] else "✗"
            lines.append(
                f"| {i} | {r['run']} | {ok} | {r['total_tokens']} | {r['success_per_token']:.6f} "
                f"| {r['duration_sec']} | {r['model_calls']} | {r['tool_calls']} | {r['cost_usd']:.6f} |"
            )

        output = "\n".join(lines)

        # Also save to file
        rankings_path = os.path.join(self.results_base_dir, "RANKINGS.md")
        with open(rankings_path, "w", encoding="utf-8") as f:
            f.write(output)

        return output
