# Agent Instructions: Tools Token Economy Benchmark

You are an expert AI agent working on a research framework designed to evaluate the token-efficiency and task-efficiency of coding agents.

## Core Mandates
- **Clean Architecture**: Strictly maintain separation between layers (Core, Features, Orchestrator).
- **Vertical Feature Sliced Design (VFSD)**: Organize code by features (e.g., isolation, telemetry, tools) rather than technical roles.
- **TDD First**: Every feature must have a corresponding test in `tests/` before implementation.
- **WSL2 Compatibility**: Ensure all shell commands and path manipulations are POSIX-compliant for WSL2 environments.
- **Token Awareness**: Minimize unnecessary file reads. Use precise `grep` or `rg` commands to locate code.

## Workflow
1. **Research**: Systematically map the codebase.
2. **Strategy**: Propose a plan following the existing architectural patterns.
3. **Execution**: Implement changes surgically.
4. **Validation**: Run `pytest` and `ruff check` to ensure quality.

## Technical Stack
- **Runtime**: Python 3.12+ (WSL2 Ubuntu)
- **Package Manager**: `uv`
- **Data Validation**: `pydantic` (v2)
- **Tokenization**: `tiktoken` (for Gemini context estimation)
- **Configuration**: `pyyaml` (YAML parser)
- **Quality Assurance**: `pytest`, `pytest-mock`, `ruff`
- **Agent Framework**: `OpenCode`

## Documentation
- Refer to `docs/ARCHITECTURE.md` for the system design.
- Refer to `docs/ROADMAP.md` for task status.
- Refer to `docs/SDD.md` for data contracts.
