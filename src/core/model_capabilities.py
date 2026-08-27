"""Model capabilities: serialization, upstream normalization, and auto-cache.

Two layers feed the /v1/models responses:

1. MANUAL layer — ``config/model_info.yaml`` (operator-curated, stored schema).
2. AUTO-CACHE layer — ``CapabilitiesCache``, populated from upstream ``/models``
   responses by a background task and persisted to ``data/model_cache.json``.

ARCH: the hot path (/v1/models, /v1/models/{id}) NEVER touches the network.
Capabilities are read from the in-memory merged store. Only the background
refresh task (and the optional ``?refresh=true`` debug flag) go upstream.

INVARIANT: model_info.yaml ALWAYS wins over the auto-cache. Both layers store
the SAME normalized shape, so a merge between them is well-defined. Lists are
*replaced* (not concatenated) so a manual ``input_modalities`` override is not
duplicated by the cache — unlike ``utils.deep_merge`` which concatenates lists.
"""
# SYSTEM: model-capabilities — manual layer + auto-cache + render
import asyncio
import json
import os
import tempfile
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from .logging import logger
from ..providers import get_provider_instance

# Full set of OpenRouter pricing keys emitted in responses; missing -> "0".
_PRICING_KEYS = (
    "prompt",
    "completion",
    "request",
    "image",
    "web_search",
    "internal_reasoning",
    "input_cache_read",
)


# ---------------------------------------------------------------------------
# Serialization (stored form -> response form)
# ---------------------------------------------------------------------------

def _format_price(value: Any) -> str:
    """Format a per-token price as a plain decimal string, never exponential.

    e.g. 4.35e-07 -> "0.000000435", 0 -> "0", 0.001 -> "0.001".
    # WHY: a raw float like 4.35e-07 serializes to "4.35e-07" in JSON, which
    # breaks clients that parse the price with a non-exponent float parser.
    """
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return "0"
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s else "0"


def _render_pricing(pricing: Dict[str, Any]) -> Dict[str, str]:
    """Render a stored pricing dict (numbers) into the full OpenRouter key set (strings)."""
    result: Dict[str, str] = {}
    for key in _PRICING_KEYS:
        result[key] = _format_price(pricing.get(key, 0))
    return result


def _build_modality(input_modalities, output_modalities) -> str:
    """Build the OpenRouter-style modality string, e.g. 'text+image->text'."""
    inp = "+".join(input_modalities) if input_modalities else ""
    out = "+".join(output_modalities) if output_modalities else ""
    if inp and out:
        return f"{inp}->{out}"
    return inp or out or ""


def render_capabilities(stored: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize the STORED capability form into the response shape.

    Single source of truth for all derived fields:
    ``architecture.modality``, ``supports_vision``, ``top_provider`` (mirrors
    context_length / max_completion_tokens / is_moderated), flat
    ``max_completion_tokens`` (already stored), string ``pricing`` with the full
    key set, and ``per_request_limits: null``.

    Empty input -> empty output, so models without any capability data keep the
    bare OpenAI object shape (no spurious fields).
    """
    if not stored:
        return {}

    out = dict(stored)

    arch = out.get("architecture")
    if isinstance(arch, dict) and arch:
        in_mods = arch.get("input_modalities") or []
        out_mods = arch.get("output_modalities") or []
        rendered_arch = dict(arch)
        modality = _build_modality(in_mods, out_mods)
        if modality:
            rendered_arch["modality"] = modality
        out["architecture"] = rendered_arch
        # supports_vision: convenience flag for harnesses that don't read input_modalities.
        out["supports_vision"] = "image" in in_mods

    # top_provider mirrors the flat fields (OpenRouter canonical location).
    top_provider: Dict[str, Any] = {}
    if out.get("context_length") is not None:
        top_provider["context_length"] = out["context_length"]
    if out.get("max_completion_tokens") is not None:
        top_provider["max_completion_tokens"] = out["max_completion_tokens"]
    if out.get("is_moderated") is not None:
        top_provider["is_moderated"] = bool(out["is_moderated"])
    if top_provider:
        out["top_provider"] = top_provider

    pricing = out.get("pricing")
    if isinstance(pricing, dict):
        out["pricing"] = _render_pricing(pricing)

    out["per_request_limits"] = None
    return out


# ---------------------------------------------------------------------------
# Merge (cache + manual override)
# ---------------------------------------------------------------------------

def merge_capabilities(base: Optional[Dict[str, Any]], override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Deep-merge two STORED-form dicts where ``override`` wins.

    Nested dicts recurse; lists and scalars are *replaced* by override (NOT
    concatenated — contrast with utils.deep_merge). This lets a manual
    ``architecture.input_modalities`` override the cache without duplication.
    """
    result: Dict[str, Any] = dict(base) if isinstance(base, dict) else {}
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_capabilities(result[key], value)
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Upstream normalization (raw /models entry -> STORED form)
# ---------------------------------------------------------------------------

def _parse_price(value: Any) -> float:
    """Parse an OpenRouter string price into a float; 0.0 on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_openrouter_shape(raw: Dict[str, Any]) -> bool:
    """Detect an OpenRouter /models entry (rich metadata)."""
    return (
        isinstance(raw.get("context_length"), int)
        or isinstance(raw.get("top_provider"), dict)
        or (isinstance(raw.get("architecture"), dict) and "input_modalities" in raw["architecture"])
        or isinstance(raw.get("pricing"), dict)
    )


def _has_llama_server_meta(raw: Dict[str, Any]) -> bool:
    """Detect a llama-server /models entry (meta.n_ctx / n_ctx_train, or capabilities)."""
    meta = raw.get("meta")
    if isinstance(meta, dict) and (
        isinstance(meta.get("n_ctx"), int) or isinstance(meta.get("n_ctx_train"), int)
    ):
        return True
    return isinstance(raw.get("capabilities"), list)


def _normalize_openrouter(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize an OpenRouter /models entry into the STORED form."""
    out: Dict[str, Any] = {}
    if isinstance(raw.get("context_length"), int):
        out["context_length"] = raw["context_length"]

    # top_provider.max_completion_tokens -> flat (stored canonical location).
    tp = raw.get("top_provider")
    if isinstance(tp, dict):
        if isinstance(tp.get("max_completion_tokens"), int):
            out["max_completion_tokens"] = tp["max_completion_tokens"]
        if "is_moderated" in tp:
            out["is_moderated"] = bool(tp["is_moderated"])

    arch = raw.get("architecture")
    if isinstance(arch, dict):
        new_arch: Dict[str, Any] = {}
        if arch.get("input_modalities"):
            new_arch["input_modalities"] = list(arch["input_modalities"])
        if arch.get("output_modalities"):
            new_arch["output_modalities"] = list(arch["output_modalities"])
        if arch.get("tokenizer"):
            new_arch["tokenizer"] = arch["tokenizer"]
        if arch.get("instruct_type"):
            new_arch["instruct_type"] = arch["instruct_type"]
        if new_arch:
            out["architecture"] = new_arch

    if isinstance(raw.get("supported_parameters"), list):
        out["supported_parameters"] = list(raw["supported_parameters"])

    pricing = raw.get("pricing")
    if isinstance(pricing, dict):
        new_pricing: Dict[str, float] = {}
        for key in _PRICING_KEYS:
            if pricing.get(key) is not None:
                new_pricing[key] = _parse_price(pricing[key])
        if new_pricing:
            out["pricing"] = new_pricing

    if raw.get("name"):
        out["name"] = raw["name"]
    if raw.get("description"):
        out["description"] = raw["description"]
    return out


def _normalize_llama_server(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a llama-server /models entry into the STORED form.

    Reads context from meta.n_ctx (the runtime window) falling back to
    n_ctx_train, and detects vision from the ``capabilities`` array (llama-server
    lists "multimodal" when an mmproj is loaded). The non-standard /props
    endpoint (modalities.video/audio) is not scraped — /models is enough.
    """
    out: Dict[str, Any] = {}
    meta = raw.get("meta") or {}
    n_ctx = meta.get("n_ctx")
    if isinstance(n_ctx, int):
        out["context_length"] = n_ctx
    elif isinstance(meta.get("n_ctx_train"), int):
        out["context_length"] = meta["n_ctx_train"]

    caps = raw.get("capabilities")
    if isinstance(caps, list) and "multimodal" in {str(c).lower() for c in caps}:
        out["architecture"] = {
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
        }
    return out


def normalize_provider_model(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a raw upstream /models entry into the STORED schema.

    Dispatches on response SHAPE (not provider name) so any OpenAI-compatible
    backend is handled: OpenRouter (rich), llama-server (meta.n_ctx +
    capabilities.multimodal -> vision), or generic OpenAI (only
    id/object/owned_by -> empty, e.g. deepseek/kimi).

    Decision: upstream 'reasoning' in supported_parameters is NOT translated
    into our reasoning{} block — that block is manual-only (default_enabled is
    not expressible in the upstream shape).
    """
    if not isinstance(raw, dict):
        return {}
    if _is_openrouter_shape(raw):
        return _normalize_openrouter(raw)
    if _has_llama_server_meta(raw):
        return _normalize_llama_server(raw)
    return {}


# ---------------------------------------------------------------------------
# Capabilities cache
# ---------------------------------------------------------------------------

class CapabilitiesCache:
    """In-memory cache of upstream model capabilities, persisted to disk.

    Stores ``{model_id: {"data": <stored form>, "fetched_at": float, "source": str}}``.
    Read from disk on startup so data is available even when upstreams are down.
    On refresh failure, existing entries are retained (stale-if-error).
    """

    def __init__(self, path: str = "data/model_cache.json"):
        self._path = path
        self._data: Dict[str, Dict[str, Any]] = {}

    def load(self) -> None:
        """Read the cache from disk; ignore missing or corrupt files."""
        try:
            with open(self._path, "r") as f:
                raw = json.load(f)
        except FileNotFoundError:
            return
        except (json.JSONDecodeError, ValueError):
            logger.warning(
                f"Model cache file {self._path} is corrupt, ignoring cached capabilities",
                extra={"config": {"model_cache_path": self._path}},
            )
            return
        if not isinstance(raw, dict):
            return
        cleaned: Dict[str, Dict[str, Any]] = {}
        for model_id, entry in raw.items():
            if isinstance(entry, dict) and isinstance(entry.get("data"), dict):
                cleaned[model_id] = entry
        self._data = cleaned
        logger.info(
            f"Loaded {len(cleaned)} cached model capabilities from {self._path}",
            extra={"config": {"model_cache_entries": len(cleaned)}},
        )

    def get(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Return the STORED-form data for a model, or None if absent."""
        entry = self._data.get(model_id)
        return None if entry is None else entry.get("data")

    def get_meta(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Return provenance (source, fetched_at) for a model, or None."""
        entry = self._data.get(model_id)
        if entry is None:
            return None
        return {"source": entry.get("source"), "fetched_at": entry.get("fetched_at")}

    def upsert(self, model_id: str, data: Dict[str, Any], source: str) -> None:
        """Insert/replace a model's stored capabilities with a fresh timestamp."""
        self._data[model_id] = {
            "data": data or {},
            "fetched_at": time.time(),
            "source": source,
        }

    def persist(self) -> None:
        """Atomically write the cache to disk.

        Uses a UNIQUE temp file per write (mkstemp) so that concurrent uvicorn
        workers — each running their own refresh task and writing the same final
        path — never rename each other's source file (which would raise ENOENT
        on os.replace). Last writer wins on the final path; content is
        equivalent across workers.
        """
        directory = os.path.dirname(self._path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".model_cache.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self._data, f)
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


# ---------------------------------------------------------------------------
# Background refresh
# ---------------------------------------------------------------------------

async def refresh_provider_capabilities(
    config_manager,
    cache: CapabilitiesCache,
    provider_name: str,
    models_config: Optional[Dict[str, Any]] = None,
) -> None:
    """Refresh capabilities for every model_id backed by ``provider_name``.

    One list_models() call per provider, then distributed to all referencing
    model_ids. On any provider error: warn and KEEP existing entries
    (stale-if-error). The task takes provider instances through the registry so
    a config reload (which rebuilds the provider cache) is respected.
    """
    config = config_manager.get_config()
    providers_config = config.get("providers", {})
    if models_config is None:
        models_config = config.get("models", {})
    provider_config = providers_config.get(provider_name)
    if not provider_config:
        return

    entries = [
        (model_id, mcfg["provider_model_name"])
        for model_id, mcfg in models_config.items()
        if mcfg.get("provider") == provider_name and mcfg.get("provider_model_name")
    ]
    if not entries:
        return

    try:
        provider = await get_provider_instance(provider_name, provider_config, config_manager)
        models_data = await provider.list_models(request_id="capabilities-cache")
    except Exception as e:
        logger.warning(
            f"Capabilities refresh: list_models failed for provider '{provider_name}': {e}",
            provider_name=provider_name,
            error_type="capabilities_refresh_error",
        )
        return  # stale-if-error

    models_list = [m for m in (models_data.get("data") or []) if isinstance(m, dict)]
    # llama-server exposes vision capabilities in a parallel NATIVE "models"
    # array; the OpenAI-compatible "data" array has meta.n_ctx but not
    # capabilities. Merge them (keyed by name/id/path) so the normalizer sees
    # both context and vision from one entry.
    native_caps: Dict[str, Any] = {}
    for n in (models_data.get("models") or []):
        if isinstance(n, dict) and isinstance(n.get("capabilities"), list):
            for key in ("model", "name", "id"):
                if n.get(key):
                    native_caps[n[key]] = n["capabilities"]
    for m in models_list:
        if "capabilities" not in m:
            caps = native_caps.get(m.get("id")) or native_caps.get(m.get("name"))
            if caps:
                m["capabilities"] = caps

    raw_by_id: Dict[str, Dict[str, Any]] = {}
    for model in models_list:
        if model.get("id"):
            raw_by_id[model["id"]] = model
        for alias in (model.get("aliases") or []):
            raw_by_id.setdefault(alias, model)

    # Fallback for single-model backends (e.g. llama-server with one loaded
    # GGUF): provider_model_name is a placeholder ("dummy") that never matches
    # the upstream id/path, but the server only has one model to serve anyway.
    single_model = models_list[0] if len(models_list) == 1 else None

    for model_id, provider_model_name in entries:
        raw = raw_by_id.get(provider_model_name)
        if raw is None and single_model is not None:
            raw = single_model
        if raw:
            cache.upsert(model_id, normalize_provider_model(raw), source=provider_name)

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
            if config_manager.model_cache_enabled:
                try:
                    await refresh_all_capabilities(config_manager, cache)
                except Exception as e:
                    logger.error(f"Capabilities refresh error: {e}", exc_info=True)
            await asyncio.sleep(config_manager.model_cache_refresh_interval)
    except asyncio.CancelledError:
        logger.info("Capabilities refresh task cancelled")
        return
