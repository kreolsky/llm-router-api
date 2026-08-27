"""Provider registry with instance caching keyed by provider name."""
# SYSTEM: provider-registry — provider instances cached by name, drained on reload
import asyncio
from typing import Dict, Any, Optional

from .base import BaseProvider
from .openai import OpenAICompatibleProvider
from ..core.error_handling import ErrorType, create_error

# ARCH: cache key is the provider name (the dict key in providers.yaml).
# Each cached instance owns its own httpx pool. The cache is rebuilt atomically
# (rebuild_provider_cache) on startup and config reload: a temp dict is built
# under _cache_lock, then swapped in, and the previous pools are closed in the
# background. On rebuild failure the old cache is retained.
_provider_cache: Dict[str, BaseProvider] = {}

# ARCH: guards the read-create-store path so two concurrent lookups for an
# uncached provider cannot both build and store (leaking one httpx pool).
_cache_lock = asyncio.Lock()


def _build_provider(
    provider_name: str,
    provider_config: Dict[str, Any],
    config_manager: Optional[Any] = None,
) -> BaseProvider:
    """Pure factory: dispatch on provider type and return a new instance.

    No caching. Raises via create_error on an unknown provider type.
    """
    provider_type = provider_config.get("type")
    if provider_type == "openai":
        return OpenAICompatibleProvider(provider_config, config_manager)
    raise create_error(
        ErrorType.PROVIDER_NOT_FOUND, provider_name=provider_type, model_id="unknown"
    )


async def get_provider_instance(
    provider_name: str,
    provider_config: Dict[str, Any],
    config_manager: Optional[Any] = None,
) -> BaseProvider:
    """Return a cached provider instance, creating one if needed (under the lock).

    Instances are cached by provider_name. Config changes to an existing
    provider are not picked up until rebuild_provider_cache() runs.
    """
    cached = _provider_cache.get(provider_name)
    if cached is not None:
        return cached

    async with _cache_lock:
        # Re-check under the lock: another coroutine may have built it.
        cached = _provider_cache.get(provider_name)
        if cached is not None:
            return cached
        instance = _build_provider(provider_name, provider_config, config_manager)
        _provider_cache[provider_name] = instance
        return instance


async def _gather_closes(coros) -> None:
    """Await all close coroutines, suppressing individual failures."""
    await asyncio.gather(*coros, return_exceptions=True)


async def rebuild_provider_cache(config: Dict[str, Any], config_manager: Optional[Any]) -> None:
    """Atomically rebuild the cache from config.

    Builds a temp dict for every configured provider under _cache_lock. If any
    provider fails to build, a RuntimeError listing all failures is raised and
    the existing cache is left untouched. On success the temp dict is swapped in
    and the previous instances' pools are closed in the background.
    """
    async with _cache_lock:
        temp: Dict[str, BaseProvider] = {}
        errors = []
        for provider_name, provider_config in (config.get("providers") or {}).items():
            try:
                temp[provider_name] = _build_provider(provider_name, provider_config, config_manager)
            except Exception as e:
                errors.append(f"  - {provider_name}: {e}")
        if errors:
            # WHY: the partially-built temp instances own open httpx pools; close
            # them so a failed rebuild (e.g. one misconfigured provider) leaks nothing.
            await _gather_closes([inst.aclose() for inst in temp.values()])
            joined = "\n".join(errors)
            raise RuntimeError(
                f"Provider validation failed; refusing to start:\n{joined}"
            )
        global _provider_cache
        old_cache = _provider_cache
        _provider_cache = temp

    coros = [inst.aclose() for inst in old_cache.values()]
    if coros:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            asyncio.ensure_future(_gather_closes(coros))
        else:
            asyncio.run(_gather_closes(coros))


async def clear_provider_cache_async() -> None:
    """Await every provider's pool close, then clear the cache.

    Used on shutdown so pools are drained gracefully before the loop stops.
    Close exceptions are suppressed via return_exceptions so one failing close
    never blocks the rest.
    """
    global _provider_cache
    if not _provider_cache:
        return
    old_cache = _provider_cache
    _provider_cache = {}
    coros = [inst.aclose() for inst in old_cache.values()]
    await _gather_closes(coros)
