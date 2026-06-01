# Architecture: Tools Token Economy Benchmark

The project is built on the principles of **Clean Architecture** and **Vertical Feature Sliced Design**.

## Layers

1.  **Core (Domain)**:
    *   Entities (AgentConfig, RunMetrics, EvalResult).
    *   Interfaces/Protocols (Tool, Runner, IsolationProvider).
2.  **Features (Use Cases / Slices)**:
    *   `isolation/`: `GitIsolationProvider` implementation (Git Worktree).
    *   `token_accounting/`: Token counting logic.
    *   `agent_integration/`: OpenCode adapters.
    *   `evaluation/`: Evaluation engine.
    *   `tool_registry/`: Specific tool implementations (`rg`, `grep`, `ast`).
3.  **Infrastructure (External APIs)**:
    *   Gemini API client.
    *   Shell (subprocess) executor.
4.  **Orchestrator (Application/Presentation)**:
    *   `benchmark.py`: Main loop controlling the runs.

## Data Flow

```text
Orchestrator 
  -> Configuration Loader
  -> Isolation Provider (Setup Worktree)
  -> OpenCode Runner (Inject Tools)
    -> Thinking Loop (Agent)
      -> Tool Call -> Tool Registry -> Shell/API
      -> Agent Output -> Patch Applier
  -> Evaluation Engine (Run Tests)
  -> Metrics Aggregator (Collect Stats)
  -> Isolation Provider (Teardown)
```

## TDD Strategy

1.  Define the contract in `Core`.
2.  Write a test in `tests/features/name_of_feature/`.
3.  Implement minimal code in `src/features/`.
4.  Refactor according to `Ruff` standards.
