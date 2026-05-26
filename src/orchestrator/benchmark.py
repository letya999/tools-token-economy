import glob as _glob
import json
import logging
import os
import re
import sys
import time
from typing import Any

from src.core.config_loader import load_benchmark_configs, load_benchmark_meta
from src.core.models import EvalResult, McpServerConfig
from src.features.tool_registry.registry import ToolRegistry
from src.features.execution_validator import ExecutionValidator
from src.features.agent_integration.agno_runner import AgnoRunner
from src.features.isolation import GitIsolationProvider
from src.features.llm_judge import LLMJudge
from src.features.metrics_aggregator import MetricsAggregator
from src.features.preflight import PreflightChecker
from src.features.tool_registry.basic_tools import (
    FileReadTool,
    FileWriteTool,
    GlobTool,
    PatchApplierTool,
    ReadAllTool,
    InsertAfterTool,
)
from src.features.tool_registry.grep_tools import AstGrepTool, GitGrepTool, GrepTool, RgTool, SemgrepTool, UgrepTool
from src.features.tool_registry.lsp_tools import LspSymbolsTool
from src.features.tool_registry.semantic_tools import SimpleRagTool
from src.features.prompt_builder import build_tool_restriction_prefix
from src.features.tool_registry.shell_tool import ShellTool
from src.features.tool_registry.structural_tools import RepoMapTool, TreeSitterTool


_MCP_TOOL_REGISTRY: dict[str, McpServerConfig] = {
    "serena": McpServerConfig(
        tool_name="serena",
        command="serena",
        args_template=["start-mcp-server", "--project", "{path}"],
    ),
    "semble": McpServerConfig(
        tool_name="semble",
        command="uvx",
        args_template=["--from", "semble[mcp]", "semble"],
    ),
}


def _to_platform_path(path: str) -> str:
    """Convert a Windows-style path (C:\\...) to /mnt/c/... when running in WSL."""
    if sys.platform == "win32":
        return path
    m = re.match(r'^([A-Za-z])[:/\\](.*)', path.replace("\\", "/"))
    if m:
        drive = m.group(1).lower()
        rest = m.group(2).lstrip("/")
        return f"/mnt/{drive}/{rest}"
    return path


from src.features.cost_guard import CostGuard, BudgetExceededError


class BenchmarkOrchestrator:
    """
    Main orchestrator for running the benchmark suite.
    """

    def __init__(
        self,
        repo_path: str,
        configs_path: str,
        results_dir: str,
        worktree_base: str = "worktrees",
        dry_run: bool = False,
        timeout_sec: int = 600,
        **_kwargs,
    ):
        self.repo_path = os.path.abspath(_to_platform_path(repo_path))
        self.meta = load_benchmark_meta(configs_path)
        self.configs = load_benchmark_configs(configs_path)
        self.results_dir = os.path.abspath(results_dir)
        self.worktree_base = os.path.abspath(_to_platform_path(worktree_base))
        self.dry_run = dry_run
        self.timeout_sec = self.meta.timeout_sec if self.meta else timeout_sec
        self.test_cmd = self.meta.test_cmd if self.meta else _kwargs.get("test_cmd", "uv run pytest")
        self.validation_cmd = self.meta.validation_cmd if self.meta else None
        self.aggregator = MetricsAggregator(self.results_dir)
        self.isolation = GitIsolationProvider(self.repo_path, self.worktree_base)
        self.cost_guard = CostGuard(
            max_suite_usd=_kwargs.get("max_suite_usd", self.meta.max_cost_usd_suite if self.meta else 5.0),
            max_config_usd=_kwargs.get("max_config_usd", self.meta.max_cost_usd_config if self.meta else 0.15),
            max_tokens_per_config=_kwargs.get("max_tokens_per_config", self.meta.max_tokens_per_config if self.meta else 500_000),
        )

        os.makedirs(self.worktree_base, exist_ok=True)

        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
        self.logger = logging.getLogger("Orchestrator")

    def _run_preflight(self, selected_ids: list[str] | None = None) -> None:
        """Run pre-flight checks; raises PreflightError if any critical check fails."""
        checker = PreflightChecker(
            repo_path=self.repo_path,
            configs=self.configs,
            test_cmd=self.test_cmd,
            dry_run=self.dry_run,
            selected_ids=selected_ids,
        )
        checker.run()

    def _get_tools_for_config(self, config: Any, worktree_path: str) -> list[Any]:
        """Instantiate regular (non-MCP) tools based on config."""
        registry = ToolRegistry(worktree_path)
        tools = []
        for t_name in config.tools:
            tool = registry.get_tool(t_name)
            if tool:
                tools.append(tool)
        return tools

    def _get_mcp_configs_for_config(self, config: Any) -> list[McpServerConfig]:
        """Return McpServerConfig instances for any MCP-backed tools in config."""
        return [_MCP_TOOL_REGISTRY[t] for t in config.tools if t in _MCP_TOOL_REGISTRY]

    def _preingest_rag_tools(self, tools: list, config_id: str) -> None:
        """Pre-build RAG index via ToolValidator.prepare()."""
        # We need a registry instance, use repo_path for ingestion
        registry = ToolRegistry(self.repo_path)
        
        for tool in tools:
            validator = registry.get_validator(tool.name)
            if validator:
                self.logger.info("[%s] Preparing tool: %s", config_id, tool.name)
                t0 = time.time()
                res = validator.prepare(self.repo_path)
                elapsed = time.time() - t0
                if res.passed:
                    self.logger.info("[%s] Preparation complete for %s (%.1fs): %s", config_id, tool.name, elapsed, res.detail)
                elif not res.skipped:
                    self.logger.warning("[%s] Preparation failed for %s: %s", config_id, tool.name, res.detail)

    def _inject_serena_project_config(self, worktree_path: str) -> None:
        """Write a minimal .serena/project.yml via SerenaValidator.configure()."""
        registry = ToolRegistry(worktree_path)
        validator = registry.get_validator("serena")
        if validator:
            validator.configure(worktree_path)

    def _capture_baseline(self) -> int:
        """Capture baseline test pass count from the original repository."""
        self.logger.info("Capturing baseline test pass count...")
        try:
            validator = ExecutionValidator(self.repo_path)
            res = validator.validate(
                validation_cmd=self.validation_cmd,
                test_cmd=self.test_cmd,
                baseline_pass_count=None  # We ARE the baseline
            )
            self.logger.info("Baseline captured: %d passed", res.tests_passed)
            return res.tests_passed
        except Exception as e:
            self.logger.warning("Failed to capture baseline: %s", e)
            return 0

    def run_suite(self, task_description: str, config_ids: list[str] | None = None):
        """Runs configurations sequentially. Pass config_ids to run a subset."""
        self._run_preflight(selected_ids=config_ids)
        self.logger.info("Starting benchmark suite (Dry Run: %s).", self.dry_run)

        configs = [c for c in self.configs if c.id in config_ids] if config_ids else self.configs
        if config_ids:
            self.logger.info("Running subset: %s", config_ids)

        baseline_pass_count = self._capture_baseline() if not self.dry_run else 0
        timestamp = time.strftime("%Y%m%d_%H%M%S")

        for config in configs:
            try:
                self.cost_guard.check_suite_budget(config.id)
            except BudgetExceededError as e:
                self.logger.error(str(e))
                break

            self.logger.info("Running config: %s (%s)", config.id, config.name)
            run_id = f"run_{timestamp}_{config.id}"
            worktree_path = None
            tools = []
            try:
                run_dir = os.path.join(self.results_dir, run_id)
                os.makedirs(run_dir, exist_ok=True)
                log_path = os.path.join(run_dir, "agent_messages.json")

                worktree_path = self.isolation.setup(run_id)
                if "serena" in config.tools:
                    self._inject_serena_project_config(worktree_path)
                tools = self._get_tools_for_config(config, worktree_path)
                if not self.dry_run:
                    self._preingest_rag_tools(tools, config.id)
                mcp_configs = self._get_mcp_configs_for_config(config)

                runner = AgnoRunner(
                    config, tools,
                    mcp_configs=mcp_configs,
                    mock=self.dry_run,
                    timeout_sec=self.timeout_sec,
                    run_dir=run_dir,
                    validation_cmd=self.validation_cmd,
                    baseline_pass_count=baseline_pass_count,
                )

                prefix = build_tool_restriction_prefix(config)
                full_task = (prefix + task_description) if prefix else task_description
                run_metrics = runner.run(full_task, worktree_path=worktree_path, test_cmd=self.test_cmd, log_path=log_path)
                
                # Record usage
                self.cost_guard.record(config.id, run_metrics.cost_usd, run_metrics.total_tokens)

                # LLM Judge Evaluation
                try:
                    messages_data = []
                    if os.path.exists(log_path):
                        with open(log_path, encoding="utf-8") as f:
                            messages_data = json.load(f)
                    
                    patch_path = os.path.join(run_dir, "final.patch")
                    patch_content = None
                    if os.path.exists(patch_path):
                        with open(patch_path, encoding="utf-8") as f:
                            patch_content = f.read()

                    judge = LLMJudge()
                    report = judge.evaluate(
                        task_description=full_task,
                        agent_messages=messages_data,
                        patch=patch_content,
                        config_tools=config.tools,
                        tests_passed=run_metrics.tests_passed,
                        tests_total=run_metrics.tests_passed + run_metrics.errors,
                        success=run_metrics.success
                    )
                    run_metrics = run_metrics.model_copy(update={
                        "task_solved_score": report.task_solved_score,
                        "tool_correctness_score": report.tool_correctness_score,
                        "judge_reasoning_task": report.task_solved_reasoning,
                        "judge_reasoning_tools": report.tool_correctness_reasoning,
                        "judge_model": report.judge_model
                    })
                except Exception as e:
                    self.logger.warning(f"LLM Judge failed for config {config.id}: {e}")

                final_result = EvalResult(
                    run_id=run_id,
                    config_id=config.id,
                    metrics=run_metrics,
                    success=run_metrics.success,
                    error=None,
                    patch=None,
                )

                save_path = self.aggregator.save_run(final_result)
                self.logger.info("Config %s finished. Results: %s", config.id, save_path)

            except Exception:
                self.logger.exception("Error running config %s", config.id)
            finally:
                for tool in tools:
                    if hasattr(tool, "close"):
                        try:
                            tool.close()
                        except Exception:  # noqa: S110
                            pass
                if worktree_path:
                    self.isolation.teardown(run_id)

        self.logger.info("Benchmark suite completed.")
        rankings = self.aggregator.generate_rankings()
        self.logger.info("Rankings generated:\n%s", rankings)

    def run_failed_configs(self, task_description: str, run_timestamp: str | None = None, config_ids: list[str] | None = None):
        """
        Re-runs only configs that previously failed in a given benchmark run.
        """
        self._run_preflight()

        if run_timestamp is None:
            all_dirs = sorted(_glob.glob(os.path.join(self.results_dir, "run_*")))
            timestamps = sorted({
                os.path.basename(d)[4:19]
                for d in all_dirs
                if os.path.isdir(d) and len(os.path.basename(d)) > 19
            })
            if not timestamps:
                raise RuntimeError(f"No previous runs found in {self.results_dir}")
            run_timestamp = timestamps[-1]

        self.logger.info("Retrying failed configs from run: %s", run_timestamp)

        failed_config_ids = []
        pattern = os.path.join(self.results_dir, f"run_{run_timestamp}_*")
        for run_dir in sorted(_glob.glob(pattern)):
            if not os.path.isdir(run_dir):
                continue
            metrics_path = os.path.join(run_dir, "metrics.json")
            if not os.path.exists(metrics_path):
                dir_name = os.path.basename(run_dir)
                failed_config_ids.append(dir_name[20:])
                continue
            with open(metrics_path) as f:
                metrics = json.load(f)
            if not metrics.get("success", False):
                dir_name = os.path.basename(run_dir)
                failed_config_ids.append(dir_name[20:])

        if config_ids:
            failed_config_ids = [c for c in failed_config_ids if c in config_ids]

        if not failed_config_ids:
            self.logger.info("No failed configs found for run %s - nothing to retry.", run_timestamp)
            return

        self.logger.info("Found %d failed configs: %s", len(failed_config_ids), failed_config_ids)

        configs_to_retry = [c for c in self.configs if c.id in failed_config_ids]
        baseline_pass_count = self._capture_baseline() if not self.dry_run else 0

        for config in configs_to_retry:
            try:
                self.cost_guard.check_suite_budget(config.id)
            except BudgetExceededError as e:
                self.logger.error(str(e))
                break

            run_id = f"run_{run_timestamp}_{config.id}"
            worktree_path = None
            tools = []
            self.logger.info("Retrying config: %s (%s)", config.id, config.name)
            try:
                run_dir = os.path.join(self.results_dir, run_id)
                os.makedirs(run_dir, exist_ok=True)
                log_path = os.path.join(run_dir, "agent_messages.json")

                worktree_path = self.isolation.setup(run_id)
                if "serena" in config.tools:
                    self._inject_serena_project_config(worktree_path)
                tools = self._get_tools_for_config(config, worktree_path)
                if not self.dry_run:
                    self._preingest_rag_tools(tools, config.id)
                mcp_configs = self._get_mcp_configs_for_config(config)
                runner = AgnoRunner(
                    config, tools,
                    mcp_configs=mcp_configs,
                    mock=self.dry_run,
                    timeout_sec=self.timeout_sec,
                    run_dir=run_dir,
                    validation_cmd=self.validation_cmd,
                    baseline_pass_count=baseline_pass_count,
                )
                prefix = build_tool_restriction_prefix(config)
                full_task = (prefix + task_description) if prefix else task_description
                run_metrics = runner.run(full_task, worktree_path=worktree_path, test_cmd=self.test_cmd, log_path=log_path)
                
                # Record usage
                self.cost_guard.record(config.id, run_metrics.cost_usd, run_metrics.total_tokens)

                # LLM Judge Evaluation
                try:
                    messages_data = []
                    if os.path.exists(log_path):
                        with open(log_path, encoding="utf-8") as f:
                            messages_data = json.load(f)
                    
                    patch_path = os.path.join(run_dir, "final.patch")
                    patch_content = None
                    if os.path.exists(patch_path):
                        with open(patch_path, encoding="utf-8") as f:
                            patch_content = f.read()

                    judge = LLMJudge()
                    report = judge.evaluate(
                        task_description=full_task,
                        agent_messages=messages_data,
                        patch=patch_content,
                        config_tools=config.tools,
                        tests_passed=run_metrics.tests_passed,
                        tests_total=run_metrics.tests_passed + run_metrics.errors,
                        success=run_metrics.success
                    )
                    run_metrics = run_metrics.model_copy(update={
                        "task_solved_score": report.task_solved_score,
                        "tool_correctness_score": report.tool_correctness_score,
                        "judge_reasoning_task": report.task_solved_reasoning,
                        "judge_reasoning_tools": report.tool_correctness_reasoning,
                        "judge_model": report.judge_model
                    })
                except Exception as e:
                    self.logger.warning(f"LLM Judge failed for config {config.id}: {e}")

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
