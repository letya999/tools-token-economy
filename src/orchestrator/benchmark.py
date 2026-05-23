import os
import logging
from typing import List, Any
from src.core.models import AgentConfig, EvalResult, RunMetrics
from src.core.config_loader import load_benchmark_configs
from src.features.isolation import GitIsolationProvider
from src.features.agent_integration.opencode_runner import OpenCodeRunner
from src.features.evaluation import EvalEngine
from src.features.metrics_aggregator import MetricsAggregator
from src.features.tool_registry.basic_tools import FileReadTool, FileWriteTool, PatchApplierTool, GlobTool, ReadAllTool
from src.features.tool_registry.grep_tools import RgTool, GrepTool, GitGrepTool, UgrepTool, SemgrepTool
from src.features.tool_registry.structural_tools import RepoMapTool, TreeSitterTool
from src.features.tool_registry.semantic_tools import SerenaAdapterTool, SembleAdapterTool, SimpleRagTool

class BenchmarkOrchestrator:
    """
    Main orchestrator for running the benchmark suite.
    """
    def __init__(self, 
                 repo_path: str, 
                 configs_path: str, 
                 results_dir: str,
                 test_cmd: str,
                 worktree_base: str = "worktrees",
                 dry_run: bool = False):
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
        
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger("Orchestrator")

    def _get_tools_for_config(self, config: AgentConfig, worktree_path: str) -> List[Any]:
        """
        Factory method to instantiate tools based on config.
        """
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
            "test": None
        }
        
        selected_tools = []
        for t_name in config.tools:
            if t_name in tool_map and tool_map[t_name]:
                selected_tools.append(tool_map[t_name])
        
        return selected_tools

    def run_suite(self, task_description: str):
        """
        Runs all configurations sequentially.
        """
        self.logger.info(f"Starting benchmark suite with {len(self.configs)} configurations (Dry Run: {self.dry_run}).")
        
        for config in self.configs:
            self.logger.info(f"Running config: {config.id} ({config.name})")
            
            run_id = f"run_{config.id}"
            worktree_path = None
            try:
                # 1. Setup Isolation
                worktree_path = self.isolation.setup(run_id)
                
                # 2. Setup Tools
                tools = self._get_tools_for_config(config, worktree_path)
                
                # 3. Run Agent
                runner = OpenCodeRunner(config, tools, mock=self.dry_run)
                run_metrics = runner.run(task_description)
                
                # 4. Evaluate
                eval_res = self.eval_engine.evaluate(worktree_path, self.test_cmd)
                
                # 5. Aggregate Results
                final_result = EvalResult(
                    run_id=run_id,
                    config_id=config.id,
                    metrics=run_metrics,
                    success=eval_res.success,
                    error=None,
                    patch=None
                )
                
                save_path = self.aggregator.save_run(final_result)
                self.logger.info(f"Config {config.id} finished. Results saved to {save_path}")
                
            except Exception as e:
                self.logger.error(f"Error running config {config.id}: {e}", exc_info=True)
            finally:
                # 6. Teardown
                if worktree_path:
                    self.isolation.teardown(run_id)
        
        self.logger.info("Benchmark suite completed.")
