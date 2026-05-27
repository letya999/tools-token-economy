
from dataclasses import dataclass

from pydantic import BaseModel, computed_field


@dataclass
class McpServerConfig:
    tool_name: str
    command: str
    args_template: list[str]

    def resolve_args(self, worktree_path: str) -> list[str]:
        return [a.replace("{path}", worktree_path) for a in self.args_template]


class BenchmarkMeta(BaseModel):
    repo: str
    task: str
    test_cmd: str = "pytest"
    validation_cmd: str | None = None
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
    judge_reasoning_task: str = ""
    judge_reasoning_tools: str = ""
    judge_reasoning_context: str = ""
    judge_model: str = ""
    context_quality_score: float = 0.0

    @computed_field
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.tool_tokens

    @computed_field
    @property
    def cost_usd(self) -> float:
        # Pricing registry (cost per 1M tokens) - Updated May 2026
        pricing = {
            "gemini-2.0-flash": {"input": 0.1, "output": 0.4},
            "gemini-2.5-flash": {"input": 0.1, "output": 0.4},
            "gpt-4o": {"input": 2.5, "output": 10.0},
            "claude-3-5-sonnet": {"input": 3.0, "output": 15.0},
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},
            "openai/gpt-4o-mini": {"input": 0.15, "output": 0.60},
            "gpt-4.1-nano": {"input": 0.10, "output": 0.40},
            "openai/gpt-4.1-nano": {"input": 0.10, "output": 0.40},
            "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
            "openai/gpt-4.1-mini": {"input": 0.40, "output": 1.60},
            "deepseek-coder": {"input": 0.14, "output": 0.28},
            "openrouter/deepseek/deepseek-coder": {"input": 0.32, "output": 0.89},
        }

        # Default to gemini-2.0-flash pricing if unknown
        p = pricing.get(self.model_name, pricing["gemini-2.0-flash"])

        input_cost = (self.input_tokens / 1_000_000) * p["input"]
        output_cost = (self.output_tokens / 1_000_000) * p["output"]
        # Tool tokens are usually sent back to input in the next turn
        tool_cost = (self.tool_tokens / 1_000_000) * p["input"]

        return input_cost + output_cost + tool_cost
    @computed_field
    @property
    def success_per_token(self) -> float:
        if self.total_tokens == 0:
            return 0.0
        # Scale to "successes per 1M tokens" for better readability (F-016)
        return 1_000_000.0 / self.total_tokens if self.success else 0.0

class EvalResult(BaseModel):
    run_id: str
    config_id: str
    metrics: RunMetrics
    success: bool
    patch: str | None = None
    error: str | None = None
