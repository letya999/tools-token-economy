import os

from src.core.config_loader import load_benchmark_configs


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
    assert read_only.archetype == "ablation"
    assert "read" in read_only.tools
    assert "write" in read_only.tools


import tempfile
import os
import yaml
import pytest

from src.core.config_loader import (
    load_provider_config,
    load_tools_config,
    load_task_config,
    load_codebase_config,
)
from src.core.models import ProviderConfig


def test_load_provider_config(tmp_path):
    data = {"provider": "openai", "model": "openai/gpt-4.1-mini", "max_steps": 30, "temperature": 0.1}
    f = tmp_path / "provider.yaml"
    f.write_text(yaml.dump(data))
    cfg = load_provider_config(str(f))
    assert isinstance(cfg, ProviderConfig)
    assert cfg.model == "openai/gpt-4.1-mini"
    assert cfg.max_steps == 30
    assert cfg.temperature == 0.1


def test_load_tools_config_inherits_provider_model(tmp_path):
    provider_data = {"provider": "openai", "model": "openai/gpt-4.1-mini", "max_steps": 25}
    tools_data = {
        "configs": [
            {"id": "01_test", "name": "Test", "archetype": "cursor", "tools": ["read", "write"]},
        ]
    }
    pf = tmp_path / "provider.yaml"
    pf.write_text(yaml.dump(provider_data))
    tf = tmp_path / "tools.yaml"
    tf.write_text(yaml.dump(tools_data))

    provider = load_provider_config(str(pf))
    configs = load_tools_config(str(tf), provider)
    assert len(configs) == 1
    assert configs[0].model == "openai/gpt-4.1-mini"
    assert configs[0].max_steps == 25


def test_load_tools_config_explicit_override_wins(tmp_path):
    """If a config explicitly sets model/max_steps, it overrides the provider default."""
    provider_data = {"model": "openai/gpt-4.1-mini", "max_steps": 50}
    tools_data = {
        "configs": [
            {"id": "01_test", "name": "Test", "archetype": "cursor",
             "tools": ["read"], "model": "openai/gpt-4.1-nano", "max_steps": 10},
        ]
    }
    pf = tmp_path / "provider.yaml"
    pf.write_text(yaml.dump(provider_data))
    tf = tmp_path / "tools.yaml"
    tf.write_text(yaml.dump(tools_data))

    provider = load_provider_config(str(pf))
    configs = load_tools_config(str(tf), provider)
    assert configs[0].model == "openai/gpt-4.1-nano"
    assert configs[0].max_steps == 10


def test_load_task_config(tmp_path):
    data = {
        "difficulty": "medium",
        "name": "Test Task",
        "description": "  Do something.  ",
        "test_cmd": "uv run pytest",
        "timeout_sec": 600,
        "required_files": ["app/services/dagster_client.py"],
    }
    f = tmp_path / "task.yaml"
    f.write_text(yaml.dump(data))
    cfg = load_task_config(str(f))
    assert cfg.description == "Do something."  # stripped
    assert cfg.timeout_sec == 600
    assert "app/services/dagster_client.py" in cfg.required_files


def test_load_codebase_config(tmp_path):
    data = {
        "name": "myrepo",
        "github_url": "https://github.com/example/repo",
        "local_path": "/tmp/repo",
        "install_cmd": "uv sync",
    }
    f = tmp_path / "codebase.yaml"
    f.write_text(yaml.dump(data))
    cfg = load_codebase_config(str(f))
    assert cfg.name == "myrepo"
    assert cfg.local_path == "/tmp/repo"
