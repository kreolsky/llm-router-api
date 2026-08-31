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
# phases on startup and config reload: prepare_provider_cache stages the
# next cache — REUSING every live instance whose providers.yaml entry is
# unchanged and building the rest (pre-swap, fail-fast) — and
# publish_provider_cache swaps it in and drains the superseded pools
# (post-swap). On prepare failure the old cache is retained.
_provider_cache: dict[str, BaseProvider] = {}

# Staged by prepare_provider_cache, consumed by publish_provider_cache. None
# means nothing is pending publication.
_staged_cache: dict[str, BaseProvider] | None = None

# ARCH: serializes the two reload phases so a prepare cannot stage over a
# publish that is mid-swap. Lookups do not take it — they are a plain dict read.
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


# INVARIANT: the published cache is the ONLY source of provider instances —
# a lookup miss is an error, never a lazy build.
# Why: callers resolve provider_config from the config and then await, so a
# reload can publish between the two. A lazy build would take that caller's
# stale provider_config and insert a provider the operator just deleted into
# the freshly published cache, where it would serve traffic until the next
# reload. prepare_provider_cache builds every configured provider up front
# (startup and every reload), so a miss can only mean "not in the live
# config" — which is exactly PROVIDER_NOT_FOUND.
async def get_provider_instance(provider_name: str) -> BaseProvider:
    """Return the published provider instance for provider_name.

    Instances are cached by provider_name and built only by
    prepare_provider_cache. An entry left unchanged by a reload keeps its
    live instance (see the INVARIANT on _live_instance_if_unchanged);
    changed entries are picked up on the next rebuild.
    """
    cached = _provider_cache.get(provider_name)
    if cached is None:
        raise create_error(
            ErrorType.PROVIDER_NOT_FOUND, provider_name=provider_name, model_id="unknown"
        )
    return cached


async def _gather_closes(coros) -> None:
    """Await all close coroutines, suppressing individual failures."""
    await asyncio.gather(*coros, return_exceptions=True)


def _live_instance_if_unchanged(
    provider_name: str,
    provider_config: dict[str, Any],
    settings: Settings,
) -> BaseProvider | None:
    """Return the published instance when it can be carried into the staged
    cache as-is, else None.

    # INVARIANT: an unchanged provider entry is carried into the staged cache
    # as the SAME instance, never rebuilt.
    # Why: the instance owns its ProviderPool, and the pool owns the
    # semaphore. Rebuilding on an unrelated reload (all four watched files
    # trigger this callback, so a models.yaml edit qualifies) resets the
    # semaphore, letting the old pool's in-flight requests plus the new
    # pool's fresh slots exceed max_concurrent together for the drain window
    # (up to stream_read_timeout). Sameness is plain dict equality on the
    # YAML-loaded entry AND the same Settings object (frozen at construction,
    # never swapped without a restart — identity is enough). The name is
    # looked up in the NEW config's iteration, so a provider the operator
    # deleted is never carried over.
    """
    live = _provider_cache.get(provider_name)
    if live is None:
        return None
    if live.settings is not settings or live.provider_config != provider_config:
        return None
    return live


def _stale_stage_values(superseded: dict[str, BaseProvider]) -> list[BaseProvider]:
    """Values of a superseded stage that are NOT (by identity) in the
    published cache — the ones a failed/superseded prepare must close.

    # INVARIANT: a superseded stage is closed MINUS its reused instances.
    # Why: with instance reuse a staged cache can hold the very objects the
    # published cache holds; closing them on supersede would flip their
    # pool's _closed flag and permanently 503 a live provider (see
    # acquire_slot in pool.py).
    """
    live_ids = {id(inst) for inst in _provider_cache.values()}
    return [inst for inst in superseded.values() if id(inst) not in live_ids]


def _build_stage(
    config: dict[str, Any], settings: Settings
) -> tuple[dict[str, BaseProvider], list[BaseProvider], list[str]]:
    """Stage one entry per configured provider: the live instance when the
    entry is unchanged (see _live_instance_if_unchanged), a fresh build
    otherwise. Returns (temp, fresh, errors); fresh lists only the instances
    THIS stage built — the ones a failed prepare must close.
    """
    temp: dict[str, BaseProvider] = {}
    fresh: list[BaseProvider] = []
    errors: list[str] = []
    for provider_name, provider_config in (config.get("providers") or {}).items():
        reused = _live_instance_if_unchanged(provider_name, provider_config, settings)
        if reused is not None:
            temp[provider_name] = reused
            continue
        try:
            built = _build_provider(provider_name, provider_config, settings)
        except Exception as e:
            errors.append(f"  - {provider_name}: {e}")
            continue
        temp[provider_name] = built
        fresh.append(built)
    return temp, fresh, errors


async def prepare_provider_cache(config: dict[str, Any], settings: Settings) -> None:
    """Build and stage the next provider cache (phase 1 of the reload).

    Stages a temp dict for every configured provider under _cache_lock:
    unchanged entries carry their live instance, new and changed entries are
    built. If any provider fails to build, a RuntimeError listing all
    failures is raised and neither the live cache nor the staged slot is
    touched (the partially-built instances are closed so a failed prepare
    leaks nothing; reused live instances are NOT closed — they still serve
    traffic from the published cache). On success the temp dict is staged
    for publish_provider_cache — the live cache still serves traffic until
    the publish. A stage that was never published (a reload vetoed after
    this callback) is closed before being replaced, minus any instance the
    published cache still holds.
    """
    global _staged_cache
    async with _cache_lock:
        superseded = _staged_cache
        _staged_cache = None
        temp, fresh, errors = _build_stage(config, settings)
        if errors:
            # WHY: doomed holds only instances THIS prepare built, plus the
            # non-reused values of the superseded stage — a reused live
            # instance sitting in temp must survive the veto; it is still
            # serving traffic from the published cache. Both own open httpx
            # pools, so a failed prepare (e.g. one misconfigured provider)
            # leaks nothing.
            doomed = list(fresh)
            if superseded is not None:
                doomed += _stale_stage_values(superseded)
            await _gather_closes([inst.aclose() for inst in doomed])
            joined = "\n".join(errors)
            raise RuntimeError(
                f"Provider validation failed; refusing to start:\n{joined}"
            )
        _staged_cache = temp
        if superseded is not None:
            # WHY: a previous prepare whose reload never reached publish (a
            # later pre-swap callback vetoed it) left open httpx pools staged;
            # replacing the stage without closing them leaks one pool per
            # provider per vetoed reload. Reused instances are excluded — the
            # published cache still owns them.
            await _gather_closes(
                [inst.aclose() for inst in _stale_stage_values(superseded)]
            )


# INVARIANT: publish_provider_cache runs only AFTER ConfigManager has swapped
# self.config, and stays the FIRST post-swap callback.
# Why: config and cache are two views of the same providers, and whichever is
# published second defines the window. Publishing the cache first would strand
# a provider the new config still lists but the new cache no longer holds, and
# every request resolving it in that window would get a spurious 404 lasting
# until the swap. Publishing after the swap inverts the window to a provider
# the new config has just ADDED, which is not yet in the cache — reachable only
# if a coroutine runs between the swap and this callback, and reload_config
# leaves no suspension point there. The removal case, which used to serve a
# deleted provider from a lazily rebuilt cache, is gone entirely: lookups no
# longer build (see the INVARIANT on get_provider_instance).
async def publish_provider_cache() -> None:
    """Swap the staged cache in and drain the superseded pools (phase 2 of the reload).

    No-op when nothing is staged (e.g. a publish without a successful
    prepare). Instances the new cache REPLACED or dropped are closed in the
    background, bounded by their drain timeout, so live SSE streams finish
    intact.
    """
    global _provider_cache, _staged_cache
    async with _cache_lock:
        staged = _staged_cache
        if staged is None:
            return
        _staged_cache = None
        old_cache = _provider_cache
        _provider_cache = staged

    # INVARIANT: publish drains old-minus-published BY IDENTITY, never the
    # whole old cache.
    # Why: a reused instance is a value in BOTH dicts; closing it here would
    # set its pool's _closed flag under itself and every later request would
    # get a permanent 503 from acquire_slot (see pool.py) — the reuse in
    # prepare would have resurrected a dead pool. Only instances absent from
    # the published cache are superseded.
    published_ids = {id(inst) for inst in staged.values()}
    coros = [
        inst.aclose() for inst in old_cache.values()
        if id(inst) not in published_ids
    ]
    if coros:
        # publish_provider_cache is async, so a loop is always running here and
        # get_running_loop() cannot raise — the old no-loop fallback was dead
        # code inside an async def.
        task = asyncio.ensure_future(_gather_closes(coros))
        _drain_tasks.add(task)
        task.add_done_callback(_on_drain_done)


async def clear_provider_cache_async() -> None:
    """Await every provider's pool close (staged included, deduped by
    identity), then clear the cache.

    Used on shutdown so pools are drained gracefully before the loop stops.
    Close exceptions are suppressed via return_exceptions so one failing close
    never blocks the rest.
    """
    global _provider_cache, _staged_cache
    staged, _staged_cache = _staged_cache, None
    # WHY: dedupe by identity — with instance reuse the staged cache can hold
    # the very instances the published cache holds; each pool is closed once.
    seen: set[int] = set()
    coros = []
    for inst in (*_provider_cache.values(), *(staged.values() if staged else ())):
        if id(inst) not in seen:
            seen.add(id(inst))
            coros.append(inst.aclose())
    _provider_cache = {}
    await _gather_closes(coros)
