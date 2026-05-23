
import yaml

from src.core.models import AgentConfig


def load_benchmark_configs(file_path: str) -> list[AgentConfig]:
    """
    Loads agent configurations from a YAML file.
    """
    with open(file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    configs = []
    for item in data.get("configs", []):
        configs.append(AgentConfig(**item))

    return configs
