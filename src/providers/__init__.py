from typing import Dict, Any
import httpx

from .base import BaseProvider
from .openai import OpenAICompatibleProvider
from .anthropic import AnthropicProvider
from .ollama import OllamaProvider
from ..core.error_handling import ErrorHandler, ErrorContext

def get_provider_instance(provider_type: str, provider_config: Dict[str, Any], client: httpx.AsyncClient) -> BaseProvider:
    if provider_type == "openai":
        return OpenAICompatibleProvider(provider_config, client)
    elif provider_type == "anthropic":
        return AnthropicProvider(provider_config, client)
    elif provider_type == "ollama":
        return OllamaProvider(provider_config, client)
    else:
        context = ErrorContext()
        raise ErrorHandler.handle_provider_not_found(
            provider_name=provider_type,
            model_id="unknown",
            context=context
        )
