import os
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


def load_model_sweep(path: str, base_provider_cfg: ProviderConfig) -> list[ProviderConfig]:
    """
    Load a model sweep manifest, inheriting judge and settings from a base config.
    """
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    sweep = []
    for item in data.get("models", []):
        # Create a new config based on base, then update with sweep specific model/provider
        cfg_data = base_provider_cfg.model_dump()
        cfg_data.update(item)
        sweep.append(ProviderConfig(**cfg_data))
        
    return sweep


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


def load_task_suite(path: str) -> list[TaskConfig]:
    """
    Parse a task suite manifest, resolve each task file, and attach categories.
    Validates that every referenced file exists.
    """
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    suite_dir = os.path.dirname(path)
    tasks = []
    missing_files = []
    
    for item in data.get("tasks", []):
        rel_path = item.get("file")
        category = item.get("category", "")
        
        # Resolve path relative to the suite manifest
        task_path = os.path.join(suite_dir, "..", "..", rel_path) if not os.path.isabs(rel_path) else rel_path
        # fallback to direct relative if the above fails (e.g. if rel_path is already 'configs/tasks/...')
        if not os.path.exists(task_path):
            task_path = os.path.join(os.getcwd(), rel_path)
            
        if not os.path.exists(task_path):
            missing_files.append(rel_path)
            continue
            
        task_cfg = load_task_config(task_path)
        task_cfg.category = category
        tasks.append(task_cfg)
        
    if missing_files:
        raise FileNotFoundError(f"Missing task files in suite {path}: {', '.join(missing_files)}")
        
    return tasks


def load_codebase_config(file_path: str) -> CodebaseConfig:
    with open(file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return CodebaseConfig(**data)


def load_weights_config(file_path: str) -> dict:
    with open(file_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data
