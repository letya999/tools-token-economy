# Project Instructions: Tools Token Economy Benchmark

This project is a research framework for evaluating the effectiveness of tools and navigation strategies for coding agents.

## Foundation
Foundational instructions and engineering standards for this repository are defined in:
- **[AGENTS.md](./AGENTS.md)**: Core mandates, architecture, and workflow instructions.

## Key Constraints
- **Model**: gpt-4.1-mini (default), configurable in `configs/provider.yaml`
- **Sequential Only**: No parallel agent execution during benchmark runs.
- **Environment**: WSL2 Ubuntu — use `bash scripts/run_wsl.sh` to launch.
