from typing import Dict, Any, Optional, Tuple
import httpx

from .base import BaseProvider
from .openai import OpenAICompatibleProvider
from .anthropic import AnthropicProvider
from .ollama import OllamaProvider
from ..core.error_handling import ErrorHandler, ErrorContext

_provider_cache: Dict[Tuple[str, str], BaseProvider] = {}

def get_provider_instance(provider_type: str, provider_config: Dict[str, Any], client: httpx.AsyncClient, config_manager: Optional[Any] = None) -> BaseProvider:
    cache_key = (provider_type, provider_config.get("base_url", ""))
    if cache_key in _provider_cache:
        return _provider_cache[cache_key]

    if provider_type == "openai":
        instance = OpenAICompatibleProvider(provider_config, client, config_manager)
    elif provider_type == "anthropic":
        instance = AnthropicProvider(provider_config, client, config_manager)
    elif provider_type == "ollama":
        instance = OllamaProvider(provider_config, client, config_manager)
    else:
        context = ErrorContext()
        raise ErrorHandler.handle_provider_not_found(
            provider_name=provider_type,
            model_id="unknown",
            context=context
        )

    _provider_cache[cache_key] = instance
    return instance

def clear_provider_cache():
    _provider_cache.clear()
