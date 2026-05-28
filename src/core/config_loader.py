import yaml

from src.core.models import (
    AgentConfig,
    BenchmarkMeta,
    CodebaseConfig,
    ProviderConfig,
    TaskConfig,
)


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


def load_provider_config(file_path: str) -> ProviderConfig:
    with open(file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return ProviderConfig(**data)


def load_tools_config(file_path: str, provider: ProviderConfig) -> list[AgentConfig]:
    with open(file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    configs = []
    for item in data.get("configs", []):
        item.setdefault("model", provider.model)
        item.setdefault("max_steps", provider.max_steps)
        configs.append(AgentConfig(**item))
    return configs


def load_task_config(file_path: str) -> TaskConfig:
    with open(file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if "description" in data:
        data["description"] = data["description"].strip()
    return TaskConfig(**data)


def load_codebase_config(file_path: str) -> CodebaseConfig:
    with open(file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return CodebaseConfig(**data)


def load_weights_config(file_path: str) -> dict:
    with open(file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data
