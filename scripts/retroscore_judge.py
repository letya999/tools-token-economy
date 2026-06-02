#!/usr/bin/env python3
"""
Retroactive LLM judge scoring.
Re-evaluates all runs from a benchmark session using saved agent_messages.json
and final.patch, then updates metrics.json with real judge scores.

Usage (from project root in WSL venv):
  python scripts/retroscore_judge.py --session 20260601_131317 [--config-id 01_cursor_like] [--dry-run]
"""
import argparse
import glob
import json
import logging
import os
import sys
import yaml
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("retroscore")

def retroscore_session(session_id, results_dir, config_id_filter, task_name, dry_run):
    # 1. Load task config for description, success_criteria, required_files
    task_cfg_path = os.path.join("configs", "tasks", f"{task_name}.yaml")
    if not os.path.exists(task_cfg_path):
        logger.error(f"Task config not found: {task_cfg_path}")
        return

    with open(task_cfg_path) as f:
        task = yaml.safe_load(f)
    task_description = task.get("description", task.get("name", ""))
    success_criteria = task.get("success_criteria", [])
    required_files = task.get("required_files", [])

    # 2. Find all run directories matching the session
    pattern = os.path.join(results_dir, f"run_{session_id}_*")
    all_dirs = sorted(glob.glob(pattern))
    if config_id_filter:
        all_dirs = [d for d in all_dirs if config_id_filter in os.path.basename(d)]

    logger.info(f"Found {len(all_dirs)} result dirs to re-score")

    # 3. Build judge (reuse same instance across dirs to avoid repeated imports)
    from src.features.llm_judge import LLMJudge
    from src.core.models import JudgeConfig
    judge_cfg = JudgeConfig(model="gpt-5.4-nano", provider="openai", api_key_env="OPENAI_API_KEY")
    # We will create fresh instances inside the loop as per plan logic

    total = 0
    updated = 0
    errors = 0

    for run_dir in all_dirs:
        total += 1
        dir_name = os.path.basename(run_dir)
        metrics_path = os.path.join(run_dir, "metrics.json")
        messages_path = os.path.join(run_dir, "agent_messages.json")
        patch_path = os.path.join(run_dir, "final.patch")

        # Load existing metrics
        if not os.path.exists(metrics_path):
            logger.warning(f"No metrics.json in {dir_name}, skipping")
            errors += 1
            continue

        with open(metrics_path) as f:
            metrics = json.load(f)

        # Load agent messages (may not exist if agent crashed)
        messages_data = []
        if os.path.exists(messages_path):
            with open(messages_path) as f:
                messages_data = json.load(f)

        # Load patch
        patch_content = None
        if os.path.exists(patch_path):
            with open(patch_path) as f:
                patch_content = f.read()

        # Extract existing test results from metrics
        tests_passed = metrics.get("tests_passed", 0)
        tests_total = tests_passed + metrics.get("errors", 0)
        success = metrics.get("success", False)
        execution_result = metrics.get("execution_result", "not_verified")

        logger.info(f"Scoring {dir_name} ...")

        try:
            # Create fresh judge instance for each run (resets internal token counters)
            judge_run = LLMJudge(judge_config=judge_cfg, max_judge_usd=2.0, run_dir=run_dir)
            report = judge_run.evaluate(
                task_description=task_description,
                agent_messages=messages_data,
                patch=patch_content,
                config_tools=[],  # not needed for task_solved scoring
                tests_passed=tests_passed,
                tests_total=tests_total,
                success=success,
                execution_result=execution_result,
                success_criteria=success_criteria,
                required_files=required_files,
                detailed=True,
            )

            # Patch metrics.json with new judge scores
            patch_fields = {
                "task_solved_score": report.task_solved_score,
                "tool_correctness_score": report.tool_correctness_score,
                "context_quality_score": report.context_quality_score,
                "correctness_score": report.correctness_score,
                "minimality_score": report.minimality_score,
                "pattern_adherence_score": report.pattern_adherence_score,
                "tool_sequence_score": report.tool_sequence_score,
                "judge_reasoning_task": report.task_solved_reasoning,
                "judge_reasoning_tools": report.tool_correctness_reasoning,
                "judge_reasoning_context": report.context_quality_reasoning,
                "judge_reasoning_correctness": report.correctness_reasoning,
                "judge_reasoning_minimality": report.minimality_reasoning,
                "judge_reasoning_pattern": report.pattern_adherence_reasoning,
                "judge_reasoning_tool_sequence": report.tool_sequence_reasoning,
                "judge_model": report.judge_model,
                "judge_cost_usd": report.judge_cost_usd,
                "judge_input_tokens": report.judge_input_tokens,
                "judge_output_tokens": report.judge_output_tokens,
                "judge_skipped": report.judge_skipped,
            }
            metrics.update(patch_fields)

            logger.info(
                f"  {dir_name}: task_solved={report.task_solved_score:.2f}  "
                f"cost=${report.judge_cost_usd:.4f}"
            )

            if not dry_run:
                with open(metrics_path, "w") as f:
                    json.dump(metrics, f, indent=2, ensure_ascii=False)
                updated += 1
            else:
                logger.info(f"  [DRY-RUN] would write {metrics_path}")
                updated += 1

        except Exception as e:
            logger.error(f"  {dir_name}: FAILED - {e}")
            errors += 1

    logger.info(f"\nDone: {updated}/{total} updated, {errors} errors")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retroactive LLM judge scoring")
    parser.add_argument("--session", required=True, help="Session timestamp, e.g. 20260601_131317")
    parser.add_argument("--results-dir", default="results")
    parser.add_argument("--config-id", default=None, help="Filter to single config, e.g. 01_cursor_like")
    parser.add_argument("--task-name", default="aging_stale")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    retroscore_session(
        session_id=args.session,
        results_dir=args.results_dir,
        config_id_filter=args.config_id,
        task_name=args.task_name,
        dry_run=args.dry_run,
    )
