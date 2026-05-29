
import logging
import warnings
from dataclasses import dataclass, field

from pydantic import BaseModel, computed_field

_log = logging.getLogger(__name__)

@dataclass
class McpServerConfig:
    tool_name: str
    command: str
    args_template: list[str]
    warmup_call: str | None = None
    warmup_args: dict = field(default_factory=dict)

    def resolve_args(self, worktree_path: str) -> list[str]:
        return [a.replace("{path}", worktree_path) for a in self.args_template]

    def resolve_warmup_args(self, worktree_path: str) -> dict:
        return {k: v.replace("{path}", worktree_path) if isinstance(v, str) else v for k, v in self.warmup_args.items()}


class ProviderConfig(BaseModel):
    provider: str = "openai"
    model: str = "openai/gpt-4.1-mini"
    api_base: str = ""
    max_steps: int = 50
    max_iterations: int = 20
    temperature: float = 0.0
    seed: int | None = 42


class TaskConfig(BaseModel):
    difficulty: str = "medium"
    name: str = ""
    description: str = ""
    test_cmd: str = "uv run --extra dev pytest tests/unit/ -q"
    timeout_sec: int = 1200
    target_file: str | None = None
    required_files: list[str] = []
    success_criteria: list[str] = []


class CodebaseConfig(BaseModel):
    name: str = ""
    github_url: str = ""
    branch: str = "main"
    commit: str = "HEAD"
    local_path: str = ""
    install_cmd: str = "uv sync --extra dev"


class BenchmarkMeta(BaseModel):
    repo: str
    task: str
    test_cmd: str = "pytest"
    validation_cmd: str | None = None
    target_file: str | None = None
    target_test: str | None = None
    required_files: list[str] = []
    timeout_sec: int = 600
    max_cost_usd_suite: float = 5.0
    max_cost_usd_config: float = 0.15
    max_tokens_per_config: int = 500_000
    max_iterations: int = 15


class AgentConfig(BaseModel):
    id: str
    name: str
    archetype: str
    tools: list[str]
    model: str = "gemini-2.5-flash"
    max_steps: int = 50

class RunMetrics(BaseModel):
    success: bool
    eval_score: float
    input_tokens: int
    output_tokens: int
    tool_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    duration_sec: float
    model_calls: int
    tool_calls: int
    model_name: str = "gemini-2.5-flash"
    tests_passed: int = 0
    files_read: int = 0
    files_changed: int = 0
    patch_lines: int = 0
    errors: int = 0
    tool_errors: int = 0
    execution_result: str = "not_verified"
    made_changes: bool = False
    cost_exceeded: bool = False
    token_exceeded: bool = False
    task_solved_score: float = 0.0
    tool_correctness_score: float = 0.0
    correctness_score: float = 0.0
    minimality_score: float = 0.0
    pattern_adherence_score: float = 0.0
    tool_sequence_score: float = 0.0
    judge_reasoning_task: str = ""
    judge_reasoning_tools: str = ""
    judge_reasoning_context: str = ""
    judge_reasoning_correctness: str = ""
    judge_reasoning_minimality: str = ""
    judge_reasoning_pattern: str = ""
    judge_reasoning_tool_sequence: str = ""
    judge_model: str = ""
    context_quality_score: float = 0.0
    retrieval_precision: float = 0.0
    retrieval_recall: float = 0.0
    agent_cycles: int = 0
    time_to_target: int = 0
    context_waste_ratio: float = 0.0
    warmup_sec: float = 0.0
    test_stderr: str = ""

    @computed_field
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.tool_tokens

    @computed_field
    @property
    def avg_tokens_per_tool(self) -> float:
        if self.tool_calls == 0:
            return 0.0
        return self.tool_tokens / self.tool_calls

    @computed_field
    @property
    def cost_usd(self) -> float:
        # Pricing registry (cost per 1M tokens) - Updated May 2026
        pricing = {
            "gemini-2.0-flash": {"input": 0.1, "output": 0.4},
            "gemini-2.5-flash": {"input": 0.1, "output": 0.4},
            "gpt-4o": {"input": 2.5, "output": 10.0, "cached_input": 1.25},
            "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
            "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cached_input": 0.075},
            "openai/gpt-4o-mini": {"input": 0.15, "output": 0.60, "cached_input": 0.075},
            "gpt-4.1-nano": {"input": 0.10, "output": 0.40, "cached_input": 0.025},
            "openai/gpt-4.1-nano": {"input": 0.10, "output": 0.40, "cached_input": 0.025},
            "gpt-4.1-mini": {"input": 0.40, "output": 1.60, "cached_input": 0.10},
            "openai/gpt-4.1-mini": {"input": 0.40, "output": 1.60, "cached_input": 0.10},
            "deepseek-coder": {"input": 0.14, "output": 0.28},
            "openrouter/deepseek/deepseek-coder": {"input": 0.32, "output": 0.89},
        }

        model_key = self.model_name
        p = pricing.get(model_key)
        if p is None:
            # Try stripping common prefixes
            stripped = model_key.replace("openai/", "").replace("google/", "").replace("anthropic/", "")
            p = pricing.get(stripped)
            
        if p is None:
            warnings.warn(f"Unknown model pricing for '{model_key}', defaulting to gpt-4.1-mini rates.")
            p = pricing["openai/gpt-4.1-mini"]

        cached_input = self.cache_read_tokens
        non_cached_input = max(0, self.input_tokens - cached_input)
        
        input_cost = (non_cached_input / 1_000_000) * p["input"]
        cached_cost = (cached_input / 1_000_000) * p.get("cached_input", p["input"] * 0.25)
        output_cost = (self.output_tokens / 1_000_000) * p["output"]
        
        # Note: Tool tokens are already included in input_tokens in subsequent turns.
        return input_cost + cached_cost + output_cost

    @computed_field
    @property
    def success_per_token(self) -> float:
        if self.total_tokens == 0:
            return 0.0

        # Gradual SPT: Use task_solved_score (0.0 to 1.0) to reward partial success.
        # Fallback to binary 'success' if judge failed to score but tests passed.
        base_score = self.task_solved_score
        if base_score == 0.0 and self.success:
            base_score = 1.0

        # Scale to "successes per 1M tokens"
        return (base_score * 1_000_000.0) / self.total_tokens

class EvalResult(BaseModel):
    run_id: str
    config_id: str
    metrics: RunMetrics
    success: bool
    patch: str | None = None
    error: str | None = None
