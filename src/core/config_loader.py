import yaml
from typing import List
from src.core.models import AgentConfig

def load_benchmark_configs(file_path: str) -> List[AgentConfig]:
    """
    Loads agent configurations from a YAML file.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    configs = []
    for item in data.get("configs", []):
        configs.append(AgentConfig(**item))
    
    return configs
