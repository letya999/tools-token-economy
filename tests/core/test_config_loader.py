import pytest
import os
from src.core.config_loader import load_benchmark_configs
from src.core.models import AgentConfig

def test_load_benchmark_configs():
    configs_path = "configs/benchmark_configs.yaml"
    # Ensure file exists (it was created in previous step)
    assert os.path.exists(configs_path)
    
    configs = load_benchmark_configs(configs_path)
    
    assert len(configs) == 20
    assert configs[0].id == "01_cursor_like"
    assert "repo_map" in configs[0].tools
    assert configs[-1].id == "20_serena_semble"
    assert "serena" in configs[-1].tools
    assert "semble" in configs[-1].tools

    # Check a few random ones
    read_only = next(c for c in configs if c.id == "05_read_only")
    assert read_only.tools == ["read", "patch", "test"]
    assert read_only.archetype == "ablation"
