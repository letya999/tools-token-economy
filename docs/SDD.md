# Software Design Document (SDD): Benchmark Framework

## 1. Data Contracts (Entities)

### 1.1. AgentConfig
```python
class AgentConfig(BaseModel):
    id: str
    name: str
    archetype: str
    tools: List[str]
    model: str = "gemini-2.5-flash"
    max_steps: int = 50
```

### 1.2. RunMetrics
```python
class RunMetrics(BaseModel):
    success: bool
    eval_score: float
    total_tokens: int
    input_tokens: int
    output_tokens: int
    tool_tokens: int
    duration_sec: float
    model_calls: int
    tool_calls: int
    cost_usd: float
```

## 2. Tool Interfaces (Tools)

Each tool must implement the following protocol:
```python
class Tool(Protocol):
    name: str
    description: str
    async def execute(self, **kwargs) -> ToolResult: ...
```

## 3. OpenCode Integration

OpenCode will be launched within the context of a `Runner` that:
1. Initializes the environment.
2. Injects tools via the `ToolRegistry`.
3. Monitors API calls via a custom `usage_tracker`.

## 4. Evaluation Scheme

1. **Status**: Fixed / Not Fixed.
2. **Tests**: Number of passed tests before and after.
3. **Accuracy**: Comparison with a reference patch (if available).
