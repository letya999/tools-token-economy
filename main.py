"""
Tools Token Economy Benchmark Framework.

NOTE: This benchmark is optimized for native Windows execution. 
While it supports WSL2 as a fallback, running directly on Windows (win32) 
is significantly more reliable and avoids pipe deadlock/subprocess hang issues.

Prerequisites for Windows:
1. Python 3.12+
2. Git for Windows (provides grep)
3. Ripgrep: winget install BurntSushi.ripgrep.MSVC
4. Node.js + npm install -g opencode-ai
"""
import argparse
import os
import sys

from dotenv import load_dotenv

from src.core.config_loader import load_benchmark_meta
from src.orchestrator.benchmark import BenchmarkOrchestrator

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Tools Token Economy Benchmark Framework")
    parser.add_argument("--configs", default="configs/benchmark_configs.yaml", help="Path to the configs YAML")
    parser.add_argument("--results", default="results", help="Directory to save results")
    # Default outside the tools_token_economy tree so opencode detects the
    # target repo's git project, not this benchmark project.
    _default_wt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_oc_worktrees")
    parser.add_argument("--worktree-base", default=_default_wt, help="Base directory for temporary worktrees")
    parser.add_argument("--repo", help="Override repo path from YAML")
    parser.add_argument("--task", help="Override task from YAML")
    parser.add_argument("--test-cmd", help="Override test command from YAML")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run with mock agent (skips real API calls, uses simulated responses)")

    args = parser.parse_args()

    meta = load_benchmark_meta(args.configs)

    repo = args.repo or (meta.repo if meta else None)
    task = args.task or (meta.task if meta else None)
    test_cmd = args.test_cmd or (meta.test_cmd if meta else "pytest")
    timeout_sec = meta.timeout_sec if meta else 600

    if not repo or not task:
        parser.error("repo and task must be set via --repo/--task or benchmark.yaml benchmark: section")

    os.makedirs(args.results, exist_ok=True)

    orchestrator = BenchmarkOrchestrator(
        repo_path=repo,
        configs_path=args.configs,
        results_dir=args.results,
        test_cmd=test_cmd,
        worktree_base=args.worktree_base,
        dry_run=args.dry_run,
        timeout_sec=timeout_sec,
    )

    orchestrator.run_suite(task)

if __name__ == "__main__":
    main()
