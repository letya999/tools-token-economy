import pytest
import yaml
from src.core.config_loader import load_model_sweep
from src.core.models import ProviderConfig, JudgeConfig

def test_load_model_sweep(tmp_path):
    # Base config
    base = ProviderConfig(
        provider="base_p",
        model="base_m",
        temperature=0.7,
        max_steps=100,
        judge=JudgeConfig(model="judge_m")
    )
    
    # Sweep manifest
    sweep_file = tmp_path / "sweep.yaml"
    sweep_content = {
        "models": [
            {"provider": "openai", "model": "gpt-4.1-mini", "api_key_env": "K1"},
            {"provider": "anthropic", "model": "claude-3-haiku", "api_key_env": "K2"}
        ]
    }
    with open(sweep_file, "w") as f:
        yaml.dump(sweep_content, f)
        
    sweep = load_model_sweep(str(sweep_file), base)
    
    assert len(sweep) == 2
    
    # Check inheritance
    assert sweep[0].provider == "openai"
    assert sweep[0].model == "gpt-4.1-mini"
    assert sweep[0].temperature == 0.7
    assert sweep[0].max_steps == 100
    assert sweep[0].judge.model == "judge_m"
    assert sweep[0].api_key_env == "K1"
    
    assert sweep[1].provider == "anthropic"
    assert sweep[1].model == "claude-3-haiku"
    assert sweep[1].api_key_env == "K2"
