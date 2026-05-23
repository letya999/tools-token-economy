import argparse
import os
from src.orchestrator.benchmark import BenchmarkOrchestrator

def main():
    parser = argparse.ArgumentParser(description="Tools Token Economy Benchmark Framework")
    parser.add_argument("--repo", required=True, help="Path to the target repository")
    parser.add_argument("--configs", default="configs/benchmark_configs.yaml", help="Path to the configs YAML")
    parser.add_argument("--results", default="results", help="Directory to save results")
    parser.add_argument("--test-cmd", default="pytest", help="Command to run tests")
    parser.add_argument("--worktree-base", default="worktrees", help="Base directory for temporary worktrees")
    parser.add_argument("--task", required=True, help="Task description for the agent")
    parser.add_argument("--dry-run", action="store_true", 
                        help="Run with mock agent (skips real API calls, uses simulated responses)")

    args = parser.parse_args()

    # Ensure results directory exists
    os.makedirs(args.results, exist_ok=True)

    orchestrator = BenchmarkOrchestrator(
        repo_path=args.repo,
        configs_path=args.configs,
        results_dir=args.results,
        test_cmd=args.test_cmd,
        worktree_base=args.worktree_base,
        dry_run=args.dry_run
    )

    orchestrator.run_suite(args.task)

if __name__ == "__main__":
    main()
