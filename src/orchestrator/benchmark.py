import logging
import os
import shutil
import time
from typing import Any

from src.core.config_loader import load_benchmark_configs
from src.core.models import EvalResult
from src.features.agent_integration.opencode_runner import OpenCodeRunner
from src.features.evaluation import EvalEngine
from src.features.isolation import GitIsolationProvider
from src.features.metrics_aggregator import MetricsAggregator
from src.features.tool_registry.basic_tools import (
    FileReadTool,
    FileWriteTool,
    GlobTool,
    PatchApplierTool,
    ReadAllTool,
)
from src.features.tool_registry.grep_tools import GitGrepTool, GrepTool, RgTool, SemgrepTool, UgrepTool
from src.features.tool_registry.lsp_tools import LspSymbolsTool
from src.features.tool_registry.semantic_tools import SembleAdapterTool, SerenaAdapterTool, SimpleRagTool
from src.features.opencode_config import write_opencode_json
from src.features.tool_registry.shell_tool import ShellTool
from src.features.tool_registry.structural_tools import RepoMapTool, TreeSitterTool


class BenchmarkOrchestrator:
    """
    Main orchestrator for running the benchmark suite.
    """

    def __init__(
        self,
        repo_path: str,
        configs_path: str,
        results_dir: str,
        test_cmd: str,
        worktree_base: str = "worktrees",
        dry_run: bool = False,
    ):
        self.repo_path = os.path.abspath(repo_path)
        self.configs = load_benchmark_configs(configs_path)
        self.results_dir = os.path.abspath(results_dir)
        self.worktree_base = os.path.abspath(worktree_base)
        self.test_cmd = test_cmd
        self.dry_run = dry_run
        self.aggregator = MetricsAggregator(self.results_dir)
        self.isolation = GitIsolationProvider(self.repo_path, self.worktree_base)
        self.eval_engine = EvalEngine()

        os.makedirs(self.worktree_base, exist_ok=True)

        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
        self.logger = logging.getLogger("Orchestrator")

    def _validate_environment(self):
        """Pre-flight checks for required CLI tools and API keys."""
        if self.dry_run:
            return

        for cmd in ["opencode", "git"]:
            if not shutil.which(cmd):
                raise RuntimeError(f"Required CLI tool '{cmd}' not found in PATH.")

        missing_keys = set()
        for config in self.configs:
            m = config.model.lower()
            if ("gemini" in m or "google/" in m) and not any(
                os.getenv(k) for k in ["GOOGLE_API_KEY", "GEMINI_API_KEY"]
            ):
                missing_keys.add("GOOGLE_API_KEY")
            elif ("gpt-" in m or "openai/" in m) and not os.getenv("OPENAI_API_KEY"):
                missing_keys.add("OPENAI_API_KEY")
            elif ("claude-" in m or "anthropic/" in m) and not os.getenv("ANTHROPIC_API_KEY"):
                missing_keys.add("ANTHROPIC_API_KEY")
            elif "openrouter/" in m and not os.getenv("OPENROUTER_API_KEY"):
                missing_keys.add("OPENROUTER_API_KEY")

        if missing_keys:
            self.logger.warning("Potentially missing API keys: %s", sorted(list(missing_keys)))

    def _get_tools_for_config(self, config: Any, worktree_path: str) -> list[Any]:
        """Factory method to instantiate tools based on config."""
        tool_map = {
            "read": FileReadTool(worktree_path),
            "read_all": ReadAllTool(worktree_path),
            "write": FileWriteTool(worktree_path),
            "patch": PatchApplierTool(worktree_path),
            "glob": GlobTool(worktree_path),
            "rg": RgTool(worktree_path),
            "grep": GrepTool(worktree_path),
            "git_grep": GitGrepTool(worktree_path),
            "ugrep": UgrepTool(worktree_path),
            "semgrep": SemgrepTool(worktree_path),
            "tree_sitter": TreeSitterTool(worktree_path),
            "repo_map": RepoMapTool(worktree_path),
            "simple_rag": SimpleRagTool(worktree_path),
            "serena": SerenaAdapterTool(worktree_path),
            "semble": SembleAdapterTool(worktree_path),
            "lsp_symbols": LspSymbolsTool(worktree_path),
            "shell": ShellTool(worktree_path),
            "test": None,
        }
        return [tool_map[t] for t in config.tools if tool_map.get(t)]

    def run_suite(self, task_description: str):
        """Runs all configurations sequentially."""
        self._validate_environment()
        self.logger.info("Starting benchmark suite (Dry Run: %s).", self.dry_run)

        timestamp = time.strftime("%Y%m%d_%H%M%S")

        for config in self.configs:
            self.logger.info("Running config: %s (%s)", config.id, config.name)
            run_id = f"run_{timestamp}_{config.id}"
            worktree_path = None
            tools = []
            try:
                worktree_path = self.isolation.setup(run_id)
                tools = self._get_tools_for_config(config, worktree_path)

                if not self.dry_run:
                    write_opencode_json(config, worktree_path)

                runner = OpenCodeRunner(config, tools, mock=self.dry_run)
                run_metrics = runner.run(task_description, worktree_path=worktree_path)

                eval_res = self.eval_engine.evaluate(worktree_path, self.test_cmd)

                run_metrics = run_metrics.model_copy(
                    update={
                        "tests_passed": eval_res.tests_passed,
                        "eval_score": eval_res.eval_score,
                        "success": eval_res.success,
                    }
                )

                final_result = EvalResult(
                    run_id=run_id,
                    config_id=config.id,
                    metrics=run_metrics,
                    success=eval_res.success,
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
