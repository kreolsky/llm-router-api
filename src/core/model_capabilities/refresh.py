"""Background refresh orchestration for the capabilities auto-cache.

ARCH: refreshes run in the background and never block startup, and the hot
path never touches the network — only this module (and the optional
``?refresh=true`` debug flag) goes upstream. Upstream shape knowledge stays in
normalizers.py; this file only schedules and distributes.
"""
import asyncio
from typing import Any

from ...providers import get_provider_instance
from ..logging import logger
from .cache import CapabilitiesCache
from .normalizers import normalize_provider_model


def _index_upstream_models(models_list: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map every upstream id and alias to its raw entry."""
    raw_by_id: dict[str, dict[str, Any]] = {}
    for model in models_list:
        if model.get("id"):
            raw_by_id[model["id"]] = model
        for alias in (model.get("aliases") or []):
            raw_by_id.setdefault(alias, model)
    return raw_by_id


def _resolve_raw_entry(
    raw_by_id: dict[str, dict[str, Any]],
    provider_model_name: str,
    single_model: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Map a configured provider_model_name to its raw upstream entry.

    Lookup order: exact id, then OpenRouter routing-suffix base id, then the
    single-model fallback.

    OpenRouter routing suffixes (":floor", ":nitro", ":online") select a
    provider for the SAME model and are absent from /models, so an exact
    lookup misses and the model silently loses its pricing.
    # INVARIANT: the base-id fallback runs ONLY when the exact id is absent.
    # Why: variant ids that DO exist upstream (":free", ":batch") carry
    # their own pricing, and must never be overwritten by the base rate.
    """
    raw = raw_by_id.get(provider_model_name)
    if raw is None and ":" in provider_model_name:
        raw = raw_by_id.get(provider_model_name.split(":", 1)[0])
    if raw is None and single_model is not None:
        raw = single_model
    return raw


async def _fetch_upstream_models(provider_name: str) -> dict[str, Any] | None:
    """One list_models() through the registry; None on failure.

    Failure is logged by the caller-facing warning here and answered with
    stale-if-error: existing cache entries are kept.
    """
    try:
        provider = await get_provider_instance(provider_name)
        return await provider.list_models(request_id="capabilities-cache")
    except Exception as e:
        logger.warning(
            f"Capabilities refresh: list_models failed for provider '{provider_name}': {e}",
            provider_name=provider_name,
            error_type="capabilities_refresh_error",
        )
        return None


def _provider_entries(
    config: dict[str, Any],
    provider_name: str,
    models_config: dict[str, Any],
) -> list[tuple[str, str]]:
    """[(model_id, provider_model_name)] for every model backed by the provider."""
    if not config.get("providers", {}).get(provider_name):
        return []
    return [
        (model_id, mcfg["provider_model_name"])
        for model_id, mcfg in models_config.items()
        if mcfg.get("provider") == provider_name and mcfg.get("provider_model_name")
    ]


async def refresh_provider_capabilities(
    config_manager,
    cache: CapabilitiesCache,
    provider_name: str,
    models_config: dict[str, Any] | None = None,
) -> None:
    """Refresh capabilities for every model_id backed by ``provider_name``.

    One list_models() call per provider, then distributed to all referencing
    model_ids. On any provider error: warn and KEEP existing entries
    (stale-if-error). The task takes provider instances through the registry so
    a config reload (which rebuilds the provider cache) is respected.
    """
    config = config_manager.get_config()
    if models_config is None:
        models_config = config.get("models", {})
    entries = _provider_entries(config, provider_name, models_config)
    if not entries:
        return

    models_data = await _fetch_upstream_models(provider_name)
    if models_data is None:
        return  # stale-if-error

    models_list = [m for m in (models_data.get("data") or []) if isinstance(m, dict)]
    # The llama-server native "models" array rides along to the normalizer,
    # which knows what it means (see normalizers._normalize_llama_server).
    native_models = models_data.get("models") or []
    raw_by_id = _index_upstream_models(models_list)

    # Fallback for single-model backends (e.g. llama-server with one loaded
    # GGUF): provider_model_name is a placeholder ("dummy") that never matches
    # the upstream id/path, but the server only has one model to serve anyway.
    single_model = models_list[0] if len(models_list) == 1 else None

    for model_id, provider_model_name in entries:
        raw = _resolve_raw_entry(raw_by_id, provider_model_name, single_model)
        if raw:
            cache.upsert(model_id, normalize_provider_model(raw, native_models),
                         source=provider_name)

    try:
        cache.persist()
    except Exception as e:
        logger.warning(f"Capabilities cache persist failed: {e}", exc_info=True)


async def refresh_all_capabilities(config_manager, cache: CapabilitiesCache) -> None:
    """Refresh capabilities for every provider referenced by models.yaml."""
    config = config_manager.get_config()
    models_config = config.get("models", {})
    seen: set = set()
    for mcfg in models_config.values():
        provider_name = mcfg.get("provider")
        if provider_name and provider_name not in seen:
            seen.add(provider_name)
            await refresh_provider_capabilities(
                config_manager, cache, provider_name, models_config=models_config
            )


async def capabilities_refresh_loop(config_manager, cache: CapabilitiesCache) -> None:
    """Periodically refresh all provider capabilities until cancelled.

    ARCH: refreshes run in the background and never block startup. The first
    refresh runs immediately (non-blocking to the lifespan), then sleeps for
    model_cache_refresh_interval. Errors are logged but never crash the loop.
    """
    try:
        while True:
            if config_manager.settings.model_cache_enabled:
                try:
                    await refresh_all_capabilities(config_manager, cache)
                except Exception as e:
                    logger.error(f"Capabilities refresh error: {e}", exc_info=True)
            await asyncio.sleep(config_manager.settings.model_cache_refresh_interval)
    except asyncio.CancelledError:
        logger.info("Capabilities refresh task cancelled")
        return
