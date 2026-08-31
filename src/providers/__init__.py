"""Provider registry with instance caching keyed by provider name."""
# SYSTEM: provider-registry — provider instances cached by name, drained on reload
import asyncio
from typing import Any

from ..core.config_manager import Settings
from ..core.error_handling import ErrorType, create_error
from .base import BaseProvider
from .openai import OpenAICompatibleProvider

# ARCH: cache key is the provider name (the dict key in providers.yaml).
# Each cached instance owns its own httpx pool. The cache is rebuilt in TWO
# phases on startup and config reload: prepare_provider_cache builds and
# stages the new instances (pre-swap, fail-fast), publish_provider_cache
# swaps them in and drains the superseded pools (post-swap). On prepare
# failure the old cache is retained.
_provider_cache: dict[str, BaseProvider] = {}

# Staged by prepare_provider_cache, consumed by publish_provider_cache. None
# means nothing is pending publication.
_staged_cache: dict[str, BaseProvider] | None = None

# ARCH: guards the read-create-store path so two concurrent lookups for an
# uncached provider cannot both build and store (leaking one httpx pool).
_cache_lock = asyncio.Lock()

# ARCH: background drain tasks are tracked here so they are not garbage-
# collected before completion (asyncio holds only weak references to tasks).
# Same pattern as _usage_tasks in src/core/usage_db/writer.py; each task
# discards itself via a done callback. No failure logging here:
# _gather_closes runs with return_exceptions=True, so the task never raises.
_drain_tasks: set[asyncio.Task] = set()


def _on_drain_done(task: asyncio.Task) -> None:
    """Done callback: discard the finished drain task from _drain_tasks."""
    _drain_tasks.discard(task)


def _build_provider(
    provider_name: str,
    provider_config: dict[str, Any],
    settings: Settings,
) -> BaseProvider:
    """Pure factory: dispatch on provider type and return a new instance.

    No caching. Raises via create_error on an unknown provider type.
    """
    provider_type = provider_config.get("type")
    if provider_type == "openai":
        return OpenAICompatibleProvider(provider_config, settings,
                                        provider_name=provider_name)
    raise create_error(
        ErrorType.PROVIDER_NOT_FOUND, provider_name=provider_type, model_id="unknown"
    )


async def get_provider_instance(
    provider_name: str,
    provider_config: dict[str, Any],
    settings: Settings,
) -> BaseProvider:
    """Return a cached provider instance, creating one if needed (under the lock).

    Instances are cached by provider_name. Config changes to an existing
    provider are not picked up until the cache is rebuilt on reload.
    """
    cached = _provider_cache.get(provider_name)
    if cached is not None:
        return cached

    async with _cache_lock:
        # Re-check under the lock: another coroutine may have built it.
        cached = _provider_cache.get(provider_name)
        if cached is not None:
            return cached
        instance = _build_provider(provider_name, provider_config, settings)
        _provider_cache[provider_name] = instance
        return instance


async def _gather_closes(coros) -> None:
    """Await all close coroutines, suppressing individual failures."""
    await asyncio.gather(*coros, return_exceptions=True)


async def prepare_provider_cache(config: dict[str, Any], settings: Settings) -> None:
    """Build and stage the next provider cache (phase 1 of the reload).

    Builds a temp dict for every configured provider under _cache_lock. If any
    provider fails to build, a RuntimeError listing all failures is raised and
    neither the live cache nor the staged slot is touched (the partially-built
    instances are closed so a failed prepare leaks nothing). On success the
    temp dict is staged for publish_provider_cache — the live cache still
    serves traffic until the publish.
    """
    global _staged_cache
    async with _cache_lock:
        temp: dict[str, BaseProvider] = {}
        errors = []
        for provider_name, provider_config in (config.get("providers") or {}).items():
            try:
                temp[provider_name] = _build_provider(provider_name, provider_config, settings)
            except Exception as e:
                errors.append(f"  - {provider_name}: {e}")
        if errors:
            # WHY: the partially-built temp instances own open httpx pools; close
            # them so a failed prepare (e.g. one misconfigured provider) leaks nothing.
            await _gather_closes([inst.aclose() for inst in temp.values()])
            joined = "\n".join(errors)
            raise RuntimeError(
                f"Provider validation failed; refusing to start:\n{joined}"
            )
        _staged_cache = temp


# INVARIANT: publish_provider_cache runs only AFTER ConfigManager has swapped
# self.config (a post-swap callback), never as a pre-swap callback.
# Why: a pre-swap publish rebuilds the cache while get_config() still returns
# the OLD config — a request resolving a provider the new config REMOVED would
# hand its stale provider_config to get_provider_instance and re-populate the
# freshly rebuilt cache, serving a ghost provider the operator deleted.
# Publishing after the swap closes that window: the removed provider becomes
# unresolvable before the cache holding it is replaced, and any instance the
# window still built into the old cache is discarded together with it.
async def publish_provider_cache() -> None:
    """Swap the staged cache in and drain the superseded pools (phase 2 of the reload).

    No-op when nothing is staged (e.g. a publish without a successful
    prepare). The previous instances' pools are closed in the background,
    bounded by their drain timeout, so live SSE streams finish intact.
    """
    global _provider_cache, _staged_cache
    async with _cache_lock:
        staged = _staged_cache
        if staged is None:
            return
        _staged_cache = None
        old_cache = _provider_cache
        _provider_cache = staged

    coros = [inst.aclose() for inst in old_cache.values()]
    if coros:
        # publish_provider_cache is async, so a loop is always running here and
        # get_running_loop() cannot raise — the old no-loop fallback was dead
        # code inside an async def.
        task = asyncio.ensure_future(_gather_closes(coros))
        _drain_tasks.add(task)
        task.add_done_callback(_on_drain_done)


async def clear_provider_cache_async() -> None:
    """Await every provider's pool close (staged included), then clear the cache.

    Used on shutdown so pools are drained gracefully before the loop stops.
    Close exceptions are suppressed via return_exceptions so one failing close
    never blocks the rest.
    """
    global _provider_cache, _staged_cache
    coros = [inst.aclose() for inst in _provider_cache.values()]
    if _staged_cache is not None:
        # A prepared-but-unpublished stage owns open pools too; close them or
        # they outlive the shutdown drain.
        coros.extend(inst.aclose() for inst in _staged_cache.values())
        _staged_cache = None
    _provider_cache = {}
    await _gather_closes(coros)
