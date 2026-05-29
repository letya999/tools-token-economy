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

    def list_sessions(self) -> list[dict]:
        """Return metadata for all known sessions in results dir."""
        from src.features.multi_run import list_sessions
        return list_sessions(self.results_base_dir)

    def generate_session_rankings(self, session_id: str, percentile: int = 75) -> str:
        """Aggregate N reps of session_id at given percentile and print ranking table."""
        from src.features.multi_run import aggregate_session
        agg = aggregate_session(self.results_base_dir, session_id, percentile)
        
        rows = []
        for config_id, stats in agg.items():
            rows.append({
                "config_id": config_id,
                "n": stats["metadata"]["n"],
                "success_rate": stats["success_rate"],
                "total_tokens": stats["total_tokens"],
                "success_per_token": stats["success_per_token"],
                "duration_sec": round(stats["duration_sec"], 2),
                "model_calls": stats["model_calls"],
                "tool_calls": stats["tool_calls"],
                "task_solved": stats["task_solved_score"],
                "tool_correct": stats["tool_correctness_score"],
                "cost_usd": round(stats["cost_usd"], 6),
            })

        if not rows:
            return f"No results found for session {session_id} to rank."

        # Sort by success_rate desc, task_solved_score desc, success_per_token desc, total_tokens asc
        rows.sort(key=lambda r: (-r["success_rate"], -r["task_solved"], -r["success_per_token"], r["total_tokens"]))

        lines = [
            f"# Session Rankings: {session_id} (p{percentile})",
            "",
            f"Showing aggregates across multiple runs for session {session_id}.",
            "",
            "| # | Config | N | Succ% | Solved | Tools | Tokens | Success/Token | Dur(s) | Model | Tools | Cost USD |",
            "|---|--------|---|-------|--------|-------|--------|---------------|--------|-------|-------|----------|",
        ]
        for i, r in enumerate(rows, 1):
            lines.append(
                f"| {i} | {r['config_id']} | {r['n']} | {r['success_rate']:.1%} | {r['task_solved']:.2f} | {r['tool_correct']:.2f} | {int(r['total_tokens'])} | {r['success_per_token']:.8f} "
                f"| {r['duration_sec']} | {int(r['model_calls'])} | {int(r['tool_calls'])} | {r['cost_usd']:.6f} |"
            )
        output = "\n".join(lines)

        # Also save to file
        rankings_path = os.path.join(self.results_base_dir, f"RANKINGS_{session_id}_p{percentile}.md")
        with open(rankings_path, "w", encoding="utf-8") as f:
            f.write(output)

        return output

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
                    "task_solved": data.get("task_solved_score", 0.0),
                    "tool_correct": data.get("tool_correctness_score", 0.0),
                    "cost_usd": round(data.get("cost_usd", 0.0), 6),
                })
            except Exception:
                continue

        if not rows:
            return "No results found to rank."

        # Sort by success desc, task_solved_score desc, success_per_token desc, total_tokens asc
        rows.sort(key=lambda r: (-int(r["success"]), -r["task_solved"], -r["success_per_token"], r["total_tokens"]))

        lines = [
            "# Benchmark Rankings",
            "",
            "| # | Run | OK | Solved | Tools | Tokens | Success/Token | Dur(s) | Model | Tools | Cost USD |",
            "|---|-----|----|--------|-------|--------|---------------|--------|-------|-------|----------|",
        ]
        for i, r in enumerate(rows, 1):
            ok = "✓" if r["success"] else "✗"
            lines.append(
                f"| {i} | {r['run']} | {ok} | {r['task_solved']:.2f} | {r['tool_correct']:.2f} | {r['total_tokens']} | {r['success_per_token']:.8f} "
                f"| {r['duration_sec']} | {r['model_calls']} | {r['tool_calls']} | {r['cost_usd']:.6f} |"
            )
        output = "\n".join(lines)

        # Also save to file
        rankings_path = os.path.join(self.results_base_dir, "RANKINGS.md")
        with open(rankings_path, "w", encoding="utf-8") as f:
            f.write(output)

        return output
