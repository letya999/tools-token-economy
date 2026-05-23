# Agent Instructions: Tools Token Economy Benchmark

You are an expert AI agent working on a research framework designed to evaluate the token-efficiency and task-efficiency of coding agents.

## Core Mandates
- **Clean Architecture**: Strictly maintain separation between layers (Core, Features, Orchestrator).
- **Vertical Feature Sliced Design (VFSD)**: Organize code by features (e.g., isolation, telemetry, tools) rather than technical roles.
- **TDD First**: Every feature must have a corresponding test in `tests/` before implementation.
- **WSL2 Consistency**: All agent execution and tool testing happen in WSL2 Ubuntu. Ensure paths are handled correctly across Win/WSL boundaries.
- **Token Economy**: The goal is to measure `success_per_token`. Minimize context bloat.

## Workflow
1. **Research**: Map the codebase using symbolic tools (Serena/Semble) or grep.
2. **Strategy**: Propose a plan that respects the [ARCHITECTURE.md](docs/ARCHITECTURE.md).
3. **Execution**: Implement surgical changes. Use `uv run pytest` for validation.
4. **Telemetry**: Ensure all new tools/actions correctly report token usage to `RunMetrics`.

## Technical Stack
- **Runtime**: Python 3.12+ (WSL2 Ubuntu)
- **Package Manager**: `uv` (use `uv run` for all commands)
- **Data Models**: `pydantic` v2 (refer to [SDD.md](docs/SDD.md) for schemas)
- **Tokenization**: `tiktoken` (fallback) & Provider-specific metrics (primary)
- **Agent Runner**: `OpenCode` CLI (subprocess wrapper)
- **MCP Ecosystem**: Persistent sessions for `Serena` and `Semble`.

## Key Documentation
- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)**: High-level system design and layer responsibilities.
- **[SDD.md](docs/SDD.md)**: Data structures for `AgentConfig`, `RunMetrics`, and `EvalResult`.
- **[ROADMAP.md](docs/ROADMAP.md)**: Project progress and Phase 5 details.

## Tool Registry Guidelines
- All tools must inherit from `BaseTool` in `src.core.tools`.
- Tool outputs must be formatted using `self.format_result()`.
- Semantic tools (Serena/Semble) should use the persistent `McpToolClient`.
