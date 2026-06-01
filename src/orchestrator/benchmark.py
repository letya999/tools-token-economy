"""Benchmark orchestrator entry point (Redirects to benchmark_runner)."""
from src.orchestrator.benchmark_runner import (
    BenchmarkOrchestrator,
    _to_platform_path,
    _make_isolation_provider,
)
from src.features.agent_integration.agno_runner import AgnoRunner
from src.features.isolation import GitIsolationProvider, DirectCopyIsolationProvider

# For backward compatibility and test stability
BenchmarkRunner = BenchmarkOrchestrator
