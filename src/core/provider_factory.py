import os
import logging
from src.core.models import ProviderConfig

_log = logging.getLogger(__name__)

def build_agent_model(cfg: ProviderConfig):
    """
    Build and return an Agno model instance based on the provider configuration.
    Supports OpenAI, Anthropic, Google (Gemini), OpenRouter, Qwen (DashScope), and custom OpenAILike.
    """
    provider = cfg.provider.lower()
    model_id = cfg.model
    
    # Resolve API Key from environment
    api_key = os.getenv(cfg.api_key_env)
    
    common_kwargs = {
        "id": model_id,
        "temperature": cfg.temperature,
    }
    
    # Agno models handle seed differently; OpenAIChat supports it directly.
    # We pass it if present.
    if cfg.seed is not None:
        common_kwargs["seed"] = cfg.seed

    if provider == "openai":
        from agno.models.openai import OpenAIChat
        return OpenAIChat(api_key=api_key, **common_kwargs)
    
    elif provider == "anthropic":
        from agno.models.anthropic import Claude
        return Claude(api_key=api_key, **common_kwargs)
    
    elif provider in ("google", "gemini"):
        from agno.models.google import Gemini
        return Gemini(api_key=api_key, **common_kwargs)
    
    elif provider == "openrouter":
        from agno.models.openrouter import OpenRouter
        return OpenRouter(api_key=api_key, **common_kwargs)
    
    elif provider in ("qwen", "dashscope"):
        from agno.models.dashscope import DashScope
        return DashScope(api_key=api_key, **common_kwargs)
    
    elif provider in ("compatible", "custom", "openai-like"):
        from agno.models.openai.like import OpenAILike
        if not cfg.api_base:
            raise ValueError(f"Provider '{provider}' requires 'api_base' to be set in configuration.")
        return OpenAILike(api_key=api_key, base_url=cfg.api_base, **common_kwargs)
    
    else:
        supported = ["openai", "anthropic", "google", "gemini", "openrouter", "qwen", "dashscope", "compatible", "custom"]
        raise ValueError(f"Unsupported provider '{provider}'. Supported: {', '.join(supported)}")
