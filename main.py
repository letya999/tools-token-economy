import argparse
import os

from dotenv import load_dotenv

from src.orchestrator.benchmark import BenchmarkOrchestrator

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Tools Token Economy Benchmark Framework")
    parser.add_argument("--repo", required=True, help="Path to the target repository")
    parser.add_argument("--configs", default="configs/benchmark_configs.yaml", help="Path to the configs YAML")
    parser.add_argument("--results", default="results", help="Directory to save results")
    parser.add_argument("--test-cmd", default="pytest", help="Command to run tests")
    parser.add_argument("--worktree-base", default="worktrees", help="Base directory for temporary worktrees")
    task_group = parser.add_mutually_exclusive_group(required=True)
    task_group.add_argument("--task", help="Task description for the agent")
    task_group.add_argument("--task-file", help="Path to a file containing the task description (e.g. configs/current_task.txt)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run with mock agent (skips real API calls, uses simulated responses)")

    args = parser.parse_args()

    if args.task_file:
        with open(args.task_file, encoding="utf-8") as f:
            task = f.read().strip()
    else:
        task = args.task

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

    orchestrator.run_suite(task)

if __name__ == "__main__":
    main()
