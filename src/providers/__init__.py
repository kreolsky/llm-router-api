"""Provider registry with instance caching keyed by provider name."""
import asyncio
from typing import Dict, Any, Optional

from .base import BaseProvider
from .openai import OpenAICompatibleProvider
from ..core.error_handling import ErrorType, create_error

# ARCH: cache key is the provider name (the dict key in providers.yaml).
# Each cached instance owns its own httpx pool; clear_provider_cache closes
# every pool before clearing so no connections leak across config reloads.
_provider_cache: Dict[str, BaseProvider] = {}


def get_provider_instance(provider_name: str, provider_config: Dict[str, Any],
                          config_manager: Optional[Any] = None) -> BaseProvider:
    """Return a cached provider instance, creating one if needed.

    Instances are cached by provider_name. Config changes to an existing
    provider are not picked up until clear_provider_cache() is called.
    """
    # INVARIANT: cache key is provider_name; call clear_provider_cache on config reload
    if provider_name in _provider_cache:
        return _provider_cache[provider_name]

    provider_type = provider_config.get("type")
    if provider_type == "openai":
        instance = OpenAICompatibleProvider(provider_config, config_manager)
    else:
        raise create_error(ErrorType.PROVIDER_NOT_FOUND, provider_name=provider_type, model_id="unknown")

    _provider_cache[provider_name] = instance
    return instance


def _close_coros():
    """Collect aclose coroutines for every cached provider instance."""
    return [inst.aclose() for inst in _provider_cache.values()]


async def _gather_closes(coros) -> None:
    """Await all close coroutines, suppressing individual failures."""
    await asyncio.gather(*coros, return_exceptions=True)


async def clear_provider_cache_async() -> None:
    """Await every provider's pool close, then clear the cache.

    Used on shutdown so pools are drained gracefully before the loop stops.
    Close exceptions are suppressed via return_exceptions so one failing close
    never blocks the rest.
    """
    if not _provider_cache:
        return
    coros = _close_coros()
    _provider_cache.clear()
    await _gather_closes(coros)


def clear_provider_cache() -> None:
    """Close every cached provider's httpx pool, then clear the cache.

    Sync reload-callback path. Old clients finish in-flight requests then close
    best-effort; the cache is cleared synchronously so new requests get fresh
    instances built from the reloaded config.
    """
    if not _provider_cache:
        return

    coros = _close_coros()
    # Clear first so concurrent requests build fresh instances from new config,
    # while old pools drain in the background.
    _provider_cache.clear()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        asyncio.ensure_future(_gather_closes(coros))
    else:
        asyncio.run(_gather_closes(coros))




