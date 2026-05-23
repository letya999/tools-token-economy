import yaml

from src.core.models import AgentConfig, BenchmarkMeta


def load_benchmark_configs(file_path: str) -> list[AgentConfig]:
    with open(file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [AgentConfig(**item) for item in data.get("configs", [])]


def load_benchmark_meta(file_path: str) -> BenchmarkMeta | None:
    with open(file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    raw = data.get("benchmark")
    if raw is None:
        return None
    raw["task"] = raw["task"].strip()
    return BenchmarkMeta(**raw)
