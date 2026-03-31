"""Provider registry with instance caching keyed by (type, base_url)."""
from typing import Dict, Any, Optional, Tuple
import httpx

from .base import BaseProvider
from .openai import OpenAICompatibleProvider
from .ollama import OllamaProvider
from ..core.error_handling import ErrorType, create_error

_provider_cache: Dict[Tuple[str, str], BaseProvider] = {}

def get_provider_instance(provider_type: str, provider_config: Dict[str, Any], client: httpx.AsyncClient, config_manager: Optional[Any] = None) -> BaseProvider:
    """Return a cached provider instance, creating one if needed.

    Instances are cached by (provider_type, base_url). Config changes to an
    existing provider are not picked up until clear_provider_cache() is called.
    """
    # INVARIANT: cache key is (type, base_url); call clear_provider_cache on config reload
    cache_key = (provider_type, provider_config.get("base_url", ""))
    if cache_key in _provider_cache:
        return _provider_cache[cache_key]

    if provider_type == "openai":
        instance = OpenAICompatibleProvider(provider_config, client, config_manager)
    elif provider_type == "ollama":
        instance = OllamaProvider(provider_config, client, config_manager)
    else:
        raise create_error(ErrorType.PROVIDER_NOT_FOUND, provider_name=provider_type, model_id="unknown")

    _provider_cache[cache_key] = instance
    return instance

def clear_provider_cache():
    _provider_cache.clear()
