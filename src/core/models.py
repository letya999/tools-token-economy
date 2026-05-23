from typing import List, Optional
from pydantic import BaseModel, computed_field

class AgentConfig(BaseModel):
    id: str
    name: str
    archetype: str
    tools: List[str]
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
    tests_passed: int = 0
    files_read: int = 0
    files_changed: int = 0
    patch_lines: int = 0
    errors: int = 0
    
    @computed_field
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.tool_tokens
    
    @computed_field
    @property
    def cost_usd(self) -> float:
        # Approximate Gemini 2.5 Flash pricing: $0.1 / 1M input, $0.4 / 1M output
        input_cost = (self.input_tokens / 1_000_000) * 0.1
        output_cost = (self.output_tokens / 1_000_000) * 0.4
        tool_cost = (self.tool_tokens / 1_000_000) * 0.1 # assuming tool output goes back to input
        return input_cost + output_cost + tool_cost

    @computed_field
    @property
    def success_per_token(self) -> float:
        if self.total_tokens == 0:
            return 0.0
        return 1.0 / self.total_tokens if self.success else 0.0

class EvalResult(BaseModel):
    run_id: str
    config_id: str
    metrics: RunMetrics
    success: bool
    patch: Optional[str] = None
    error: Optional[str] = None
