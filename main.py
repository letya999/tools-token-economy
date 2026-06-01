"""
Tools Token Economy Benchmark Framework.

NOTE: This benchmark is optimized for native Windows execution.
While it supports WSL2 as a fallback, running directly on Windows (win32)
is significantly more reliable and avoids pipe deadlock/subprocess hang issues.
"""
import argparse
import os
import sys

from dotenv import load_dotenv

# Non-login WSL/Linux shells omit ~/.local/bin where uv, serena, ast-grep live.
if sys.platform != "win32":
    _user_bin = os.path.expanduser("~/.local/bin")
    if os.path.isdir(_user_bin) and _user_bin not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _user_bin + ":" + os.environ["PATH"]

from src.core.config_loader import (
    load_benchmark_configs,
    load_benchmark_meta,
    load_codebase_config,
    load_provider_config,
    load_task_config,
    load_task_suite,
    load_model_sweep,
    load_tools_config,
    load_weights_config,
)
from src.core.models import ProviderConfig, TaskConfig, CodebaseConfig
from src.orchestrator.benchmark import BenchmarkOrchestrator
from src.orchestrator.matrix import MatrixOrchestrator

load_dotenv()


def _run_setup_pipeline(args, meta, repo: str | None) -> None:
    """
    Unified setup pipeline. Runs all stages and prints PASS/FAIL per stage.
    Aborts on first critical failure.
    """
    from src.features.preflight import PreflightChecker, PreflightError

    width = 60
    print(f"\n{'=' * width}")
    print("  SETUP PIPELINE")
    print(f"{'=' * width}")

    def stage(label: str, ok: bool, detail: str = "") -> None:
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}]  {label}")
        if detail:
            print(f"         {detail}")
        if not ok:
            print(f"\n  Aborted at: {label}")
            print(f"{'=' * width}\n")
            sys.exit(1)

    # Convert Windows path to WSL /mnt/ format when running on Linux
    if repo and sys.platform != "win32":
        import re as _re
        _m = _re.match(r'^([A-Za-z])[:/\\](.+)', str(repo).replace("\\", "/"))
        if _m:
            repo = f"/mnt/{_m.group(1).lower()}/{_m.group(2).lstrip('/')}"

    # Stage 1 — platform detection
    platform = "WSL2/Linux" if sys.platform != "win32" else "Windows"
    stage("Platform detection", True, platform)

    # Stage 2 — system tool checks
    import shutil
    required_bins = ["uv", "git", "rg"]
    for b in required_bins:
        found = shutil.which(b) is not None
        stage(f"System tool: {b}", found, "" if found else f"`{b}` not found in PATH")

    # Stage 3 — Python version
    v = sys.version_info
    stage("Python >= 3.13", v >= (3, 13), f"{v.major}.{v.minor}.{v.micro}")

    # Stage 4 — target repo exists + uv sync
    if repo:
        import subprocess
        exists = os.path.isdir(repo)
        stage("Target repo exists", exists, repo)
        if exists:
            r = subprocess.run(
                ["uv", "sync", "--extra", "dev"],
                cwd=repo, capture_output=True, text=True, timeout=300,
            )
            stage("Target repo uv sync", r.returncode == 0,
                  "OK" if r.returncode == 0 else r.stderr.strip()[:120])
    else:
        stage("Target repo", False, "No repo configured — set benchmark.repo in configs YAML")

    # Stage 5 — preflight checks (tool CLIs, API keys, smoke tests)
    if repo and meta:
        try:
            configs = load_benchmark_configs(args.configs)
            provider_cfg = load_provider_config(args.provider)
            checker = PreflightChecker(
                repo_path=repo,
                configs=configs,
                test_cmd=meta.test_cmd,
                dry_run=True,
                target_file=meta.target_file,
                target_test=meta.target_test,
                provider_cfg=provider_cfg,
            )
            checker.run()
            stage("Preflight checks", True)
        except PreflightError as e:
            stage("Preflight checks", False, str(e))
        except Exception as e:
            stage("Preflight checks", False, str(e))

    print(f"\n{'=' * width}")
    print("  Setup complete. Run `python main.py` to start the benchmark.")
    print(f"{'=' * width}\n")


def _build_dashboard(results_dir: str) -> None:
    """Build a single-page HTML dashboard from latest metrics."""
    import time

    from src.features.dashboard_builder import generate_dashboard
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(results_dir, f"dashboard_{ts}.html")
    generate_dashboard(results_dir, out_path)
    print(f"Dashboard generated: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Tools Token Economy Benchmark Framework")
    
    # Configuration paths
    parser.add_argument("--provider", default="configs/provider.yaml", help="Provider config YAML")
    parser.add_argument("--tools", default="configs/tools.yaml", help="Tools/strategies config YAML")
    parser.add_argument("--task-config", default="configs/tasks/aging_stale.yaml", help="Task config YAML")
    parser.add_argument("--task-name", help="Task name to load from configs/tasks/<name>.yaml (overrides --task-config)")
    parser.add_argument("--codebase", default="configs/codebase.yaml", help="Codebase config YAML")
    parser.add_argument("--weights", default="configs/benchmark_weights.yaml", help="Benchmark weights YAML")
    parser.add_argument("--configs", default="configs/benchmark_configs.yaml",
                        help="Legacy: single combined benchmark configs YAML (backward compat)")

    # Matrix & Suite flags
    parser.add_argument("--task-suite", help="Path to a task suite manifest YAML")
    parser.add_argument("--models", help="Path to a model sweep manifest YAML")
    parser.add_argument("--matrix", action="store_true", help="Run full models x tasks matrix (requires --task-suite and --models)")
    parser.add_argument("--estimate", action="store_true", help="Estimate matrix size and cost, then exit")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation for paid runs")

    # Execution overrides
    parser.add_argument("--results", default="results", help="Directory to save results")
    _default_wt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_oc_worktrees")
    parser.add_argument("--worktree-base", default=_default_wt, help="Base directory for temporary worktrees")
    parser.add_argument("--repo", help="Override repo path from YAML")
    parser.add_argument("--task", help="Override task from YAML")
    parser.add_argument("--test-cmd", help="Override test command from YAML")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run with mock agent (skips real API calls, uses simulated responses)")
    parser.add_argument(
        "--retry-failed",
        nargs="?",
        const="latest",
        metavar="TIMESTAMP",
        help="Re-run failed configs from a previous run. Optionally specify timestamp (YYYYMMDD_HHMMSS). Defaults to latest run.",
    )
    parser.add_argument(
        "--config-ids",
        nargs="+",
        metavar="ID",
        help="Run only the specified config IDs (e.g. 02_claude_code_like 05_read_only).",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        help="Number of full benchmark repetitions (runs) to execute.",
    )
    
    # Budget overrides
    parser.add_argument("--max-matrix-usd", type=float, default=50.0, help="Max USD budget for the entire matrix run")
    parser.add_argument("--max-session-usd", type=float, default=8.0, help="Max USD budget for a single task session")

    # Maintenance & Reporting
    parser.add_argument("--doctor", action="store_true", help="Run infrastructure health checks")
    parser.add_argument("--auto-fix", action="store_true", help="Attempt to auto-fix issues found by --doctor")
    parser.add_argument("--setup", action="store_true",
                        help="Run full environment setup pipeline: tool checks, venv, deps, dry-run")
    parser.add_argument("--dashboard", action="store_true",
                        help="Build HTML dashboard from results/ and serve on localhost:8080")

    args = parser.parse_args()

    # Base configuration loading
    if args.task_name:
        args.task_config = f"configs/tasks/{args.task_name}.yaml"
        if not os.path.exists(args.task_config):
             print(f"Error: Task config not found at {args.task_config}")
             return

    provider_cfg = load_provider_config(args.provider)
    codebase_cfg = load_codebase_config(args.codebase)
    tools_cfg = load_tools_config(args.tools, provider_cfg)
    weights_cfg = load_weights_config(args.weights) if os.path.exists(args.weights) else {}
    
    # Resolve models (sweep or single)
    if args.models:
        models = load_model_sweep(args.models, provider_cfg)
    else:
        models = [provider_cfg]
        
    # Resolve tasks (suite or single)
    if args.task_suite:
        tasks = load_task_suite(args.task_suite)
    else:
        tasks = [load_task_config(args.task_config)]
        
    # Apply single-run CLI overrides to the (only) task/codebase
    if args.task:
        tasks[0] = tasks[0].model_copy(update={"description": args.task})
    if args.test_cmd:
        tasks[0] = tasks[0].model_copy(update={"test_cmd": args.test_cmd})
    if args.repo:
        codebase_cfg = codebase_cfg.model_copy(update={"local_path": args.repo})

    # Maintenance modes
    if args.doctor:
        from src.features.doctor import Doctor
        doc = Doctor(codebase_cfg.local_path or codebase_cfg.github_url)
        healthy = doc.check_all(auto_fix=args.auto_fix)
        sys.exit(0 if healthy else 1)

    if args.setup:
        meta_for_setup = type('M', (), {
            'test_cmd': tasks[0].test_cmd,
            'target_file': tasks[0].target_file,
            'target_test': tasks[0].target_file,
        })()
        _run_setup_pipeline(args, meta_for_setup, codebase_cfg.local_path)
        sys.exit(0)

    if args.dashboard:
        _build_dashboard(args.results)
        sys.exit(0)

    # Cost Estimation
    if args.estimate:
        n_configs = len(args.config_ids) if args.config_ids else len(tools_cfg)
        total_runs = len(models) * len(tasks) * n_configs * args.runs
        projected_usd = total_runs * 0.02
        projected_tokens = total_runs * 120_000
        
        print("\n" + "="*60)
        print("  MATRIX ESTIMATE")
        print("="*60)
        print(f"  Models:   {len(models)}")
        print(f"  Tasks:    {len(tasks)}")
        print(f"  Configs:  {n_configs}")
        print(f"  Runs:     {args.runs}")
        print("-"*30)
        print(f"  Total Runs:       {total_runs}")
        print(f"  Projected Cost:   ${projected_usd:.2f}")
        print(f"  Projected Tokens: {projected_tokens:,}")
        print(f"  Budget Cap:       ${args.max_matrix_usd:.2f}")
        print("="*60 + "\n")
        return

    # Dispatch logic
    is_matrix = args.matrix or args.task_suite or args.models
    
    os.makedirs(args.results, exist_ok=True)

    if is_matrix:
        if args.matrix and not (args.task_suite and args.models):
            print("Error: --matrix requires both --task-suite and --models")
            return
            
        orchestrator = MatrixOrchestrator(
            models=models,
            tasks=tasks,
            agent_configs=tools_cfg,
            codebase=codebase_cfg,
            weights=weights_cfg,
            results_dir=args.results,
            n_runs=args.runs,
            dry_run=args.dry_run,
            max_matrix_usd=args.max_matrix_usd,
        )
        orchestrator.run()
    else:
        # Standard single orchestrator behavior
        orchestrator = BenchmarkOrchestrator(
            provider_config=provider_cfg,
            tools_configs=tools_cfg,
            task_config=tasks[0],
            codebase_config=codebase_cfg,
            weights_config=weights_cfg,
            results_dir=args.results,
            worktree_base=args.worktree_base,
            dry_run=args.dry_run,
            n_runs=args.runs,
        )

        if args.retry_failed is not None:
            ts = None if args.retry_failed == "latest" else args.retry_failed
            session_id = orchestrator.run_failed_configs(run_timestamp=ts, config_ids=args.config_ids)
        else:
            session_id = orchestrator.run_suite(config_ids=args.config_ids)

        # Validity Summary for multi-run sessions
        if session_id and args.runs > 1:
            from src.features.multi_run import aggregate_session
            from src.features.stats import STATUS_OK
            
            results = aggregate_session(args.results, session_id)
            if results:
                print("\n" + "="*60)
                print("  VALIDITY SUMMARY")
                print("="*60)
                for cfg_id, stats in results.items():
                    status = stats.get("_validity_status", "unknown")
                    if status != STATUS_OK:
                        suggested = stats.get("_suggested_additional_runs", 0)
                        print(f"  [{status.upper()}] Config: {cfg_id}")
                        if suggested > 0:
                            print(f"             Suggested additional runs: {suggested}")
                print("="*60 + "\n")

if __name__ == "__main__":
    main()
