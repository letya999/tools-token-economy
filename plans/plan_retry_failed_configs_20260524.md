# Plan: Add --retry-failed flag for re-running failed benchmark configs

## Goal
Allow re-running only the failed configs from a previous benchmark run, writing results
back to the SAME original run directories so rankings stay coherent.

## Usage after implementation
```bash
# Retry failed configs from the latest run
uv run python main.py --retry-failed

# Retry failed configs from a specific run timestamp
uv run python main.py --retry-failed 20260524_204202
```

## Files to Modify

### 1. `main.py`
Add `--retry-failed` optional argument and wire it to the orchestrator.

After the existing `--dry-run` argument, add:
```python
parser.add_argument(
    "--retry-failed",
    nargs="?",
    const="latest",
    metavar="TIMESTAMP",
    help="Re-run failed configs from a previous run. Optionally specify timestamp (YYYYMMDD_HHMMSS). Defaults to latest run.",
)
```

At the bottom, replace:
```python
orchestrator.run_suite(task)
```
With:
```python
if args.retry_failed is not None:
    ts = None if args.retry_failed == "latest" else args.retry_failed
    orchestrator.run_failed_configs(task, run_timestamp=ts)
else:
    orchestrator.run_suite(task)
```

### 2. `src/orchestrator/benchmark.py`
Add `run_failed_configs` method to `BenchmarkOrchestrator` class.

Add these imports at the top of the file (after existing imports):
```python
import glob as _glob
import json
```

Add the method AFTER `run_suite`:

```python
def run_failed_configs(self, task_description: str, run_timestamp: str | None = None):
    """
    Re-runs only configs that previously failed in a given benchmark run.
    Results overwrite the original run directory entries so rankings stay coherent.
    If run_timestamp is None, uses the most recent run found in results_dir.
    """
    self._validate_environment()

    # --- Resolve timestamp ---
    if run_timestamp is None:
        # Collect unique timestamps from existing result dirs
        all_dirs = sorted(_glob.glob(os.path.join(self.results_dir, "run_*")))
        timestamps = sorted({
            os.path.basename(d)[4:19]   # chars 4-18 = "YYYYMMDD_HHMMSS"
            for d in all_dirs
            if os.path.isdir(d) and len(os.path.basename(d)) > 19
        })
        if not timestamps:
            raise RuntimeError(f"No previous runs found in {self.results_dir}")
        run_timestamp = timestamps[-1]

    self.logger.info("Retrying failed configs from run: %s", run_timestamp)

    # --- Find failed config_ids from that run ---
    failed_config_ids = []
    pattern = os.path.join(self.results_dir, f"run_{run_timestamp}_*")
    for run_dir in sorted(_glob.glob(pattern)):
        if not os.path.isdir(run_dir):
            continue
        metrics_path = os.path.join(run_dir, "metrics.json")
        if not os.path.exists(metrics_path):
            # No metrics file = the config errored out entirely, count as failed
            dir_name = os.path.basename(run_dir)
            failed_config_ids.append(dir_name[16:])  # skip "run_YYYYMMDD_HHMMSS_"
            continue
        with open(metrics_path) as f:
            metrics = json.load(f)
        if not metrics.get("success", False):
            dir_name = os.path.basename(run_dir)
            failed_config_ids.append(dir_name[16:])  # skip "run_YYYYMMDD_HHMMSS_"

    if not failed_config_ids:
        self.logger.info("No failed configs found for run %s — nothing to retry.", run_timestamp)
        return

    self.logger.info("Found %d failed configs: %s", len(failed_config_ids), failed_config_ids)

    # --- Filter to only failed configs present in current config file ---
    configs_to_retry = [c for c in self.configs if c.id in failed_config_ids]
    missing = set(failed_config_ids) - {c.id for c in configs_to_retry}
    if missing:
        self.logger.warning("Some failed configs not found in config file (skipping): %s", sorted(missing))

    # --- Re-run each failed config using the ORIGINAL run_id ---
    for config in configs_to_retry:
        run_id = f"run_{run_timestamp}_{config.id}"
        worktree_path = None
        tools = []
        self.logger.info("Retrying config: %s (%s)", config.id, config.name)
        try:
            worktree_path = self.isolation.setup(run_id)
            tools = self._get_tools_for_config(config, worktree_path)
            runner = AgnoRunner(config, tools, mock=self.dry_run, timeout_sec=self.timeout_sec)
            prefix = build_tool_restriction_prefix(config)
            full_task = (prefix + task_description) if prefix else task_description
            run_metrics = runner.run(full_task, worktree_path=worktree_path, test_cmd=self.test_cmd)

            final_result = EvalResult(
                run_id=run_id,
                config_id=config.id,
                metrics=run_metrics,
                success=run_metrics.success,
                error=None,
                patch=None,
            )
            save_path = self.aggregator.save_run(final_result)
            self.logger.info("Config %s retry done. Success=%s  Results: %s",
                             config.id, run_metrics.success, save_path)
        except Exception:
            self.logger.exception("Error retrying config %s", config.id)
        finally:
            for tool in tools:
                if hasattr(tool, "close"):
                    try:
                        tool.close()
                    except Exception:
                        pass
            if worktree_path:
                self.isolation.teardown(run_id)

    self.logger.info("Retry run complete.")
    rankings = self.aggregator.generate_rankings()
    self.logger.info("Updated rankings:\n%s", rankings)
```

## Key Design Notes
- `run_id` reuses the ORIGINAL timestamp → `aggregator.save_run` overwrites `metrics.json`
  in the original directory, keeping rankings coherent
- `dir_name[16:]` skips `"run_YYYYMMDD_HHMMSS_"` (4 + 15 + 1 = 20 chars; wait: "run_" = 4, 
  "20260524_204202" = 15, "_" = 1 → total prefix = 20 chars, so index is `[20:]` not `[16:]`)
  
  CORRECTION: use `dir_name[20:]` to extract config_id:
  - `"run_"` = 4 chars
  - `"20260524_204202"` = 15 chars  
  - `"_"` = 1 char
  - Total = 20 chars
  - So: `dir_name[20:]` gives `"01_cursor_like"`
  
  Fix the two occurrences: `dir_name[16:]` → `dir_name[20:]`

## Verification
After implementing, run:
```
wsl -- bash -lc "cd /mnt/c/Users/User/a_projects/tools_token_economy && UV_PROJECT_ENVIRONMENT=/tmp/tte_venv uv run pytest tests/ -x -q 2>&1 | tail -5"
```
All 66 tests should pass.

Then verify the CLI shows the new flag:
```
wsl -- bash -lc "cd /mnt/c/Users/User/a_projects/tools_token_economy && UV_PROJECT_ENVIRONMENT=/tmp/tte_venv uv run python main.py --help 2>&1 | grep retry"
```
