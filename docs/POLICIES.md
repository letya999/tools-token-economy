# Engineering Policies: Tools Token Economy Benchmark

This document defines the mandatory engineering standards for the repository. All agents and human contributors must adhere to these policies.

## 1. Quality & Linting Policy (Hardcore Mode)
The project uses `ruff` with a comprehensive set of rules including security, performance, and design checks.
- **Rule Enforcement**: All code MUST pass `ruff check .` before submission.
- **Complexity**: Maximum McCabe complexity is 10. Methods exceeding this must be refactored into smaller, testable units.
- **Vertical Sliced Design**: Do not create cross-feature dependencies unless necessary. Prefer duplication of small utilities over complex shared abstractions.

## 2. Security Policy
- **Subprocess Handling**: Use absolute paths for all executables. Always set `check=True` for internal infrastructure and `check=False` for agent-executed commands to capture errors gracefully.
- **Token Protection**: NEVER log API keys or raw LLM conversation history to `metrics.json`. Only aggregate counts and performance metrics are permitted.
- **Shell Execution**: Acknowledge that agents require `shell=True` for complex tasks, but ensure they operate within the `git worktree` isolation boundary.

## 3. Performance & Optimization Policy
- **Persistent Connections**: Tools that interface with external servers (e.g., MCP servers) MUST use persistent sessions. Creating/Closing processes per tool-call is prohibited due to latency impact on `duration_sec`.
- **List Comprehensions**: Prefer list comprehensions and `list.extend` over manual loops for better bytecode performance.
- **Lazy Imports**: Use optional imports for heavy libraries (like `rank_bm25`) to keep the startup time of basic tools low.

## 4. Token Efficiency Policy
- **Context Management**: The primary metric is `success_per_token`. Minimize unnecessary file reads.
- **Precise Reading**: Prefer `FileReadTool` with specific line ranges over `ReadAllTool`.
- **Accounting**: All tool outputs must contribute to `tool_tokens` in `RunMetrics`. If a tool output is too large, it should be summarized before being returned to the agent.

## 5. Validation Policy
- **TDD First**: Every bug fix or feature implementation must be accompanied by a test in `tests/`.
- **Mocking**: Use `unittest.mock` for external API calls, but ensure at least one E2E integration test exists for critical paths (like isolation setup).
- **Environment**: All tests must pass in the WSL2 Ubuntu environment.
