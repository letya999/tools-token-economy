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
    
    @computed_field
    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.tool_tokens
    
    @computed_field
    @property
    def cost_usd(self) -> float:
        # Approximate Gemini 2.5 Flash pricing: $0.1 / 1M input, $0.4 / 1M output
        # Tool tokens are essentially part of input or output context, 
        # but here we treat them as additional overhead for the benchmark.
        input_cost = (self.input_tokens / 1_000_000) * 0.1
        output_cost = (self.output_tokens / 1_000_000) * 0.4
        tool_cost = (self.tool_tokens / 1_000_000) * 0.1 # assuming tool output goes back to input
        return input_cost + output_cost + tool_cost

class EvalResult(BaseModel):
    run_id: str
    config_id: str
    metrics: RunMetrics
    patch: Optional[str] = None
    error: Optional[str] = None
