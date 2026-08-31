"""Upstream normalization: a raw /models entry -> the STORED form.

Dispatches on response SHAPE (not provider name) so any OpenAI-compatible
backend is handled: OpenRouter (rich), llama-server (meta.n_ctx +
capabilities.multimodal -> vision), or generic OpenAI (only
id/object/owned_by -> empty, e.g. deepseek/kimi).

The llama-server native-``models`` merge lives HERE, behind
``normalize_provider_model``: vision capabilities arrive in a parallel native
array of the same upstream response, and knowing that shape is normalizer
knowledge, not scheduler knowledge.
"""
from typing import Any

from .render import PRICING_KEYS


def _parse_price(value: Any) -> float:
    """Parse an OpenRouter string price into a float; 0.0 on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _is_openrouter_shape(raw: dict[str, Any]) -> bool:
    """Detect an OpenRouter /models entry (rich metadata)."""
    return (
        isinstance(raw.get("context_length"), int)
        or isinstance(raw.get("top_provider"), dict)
        or (isinstance(raw.get("architecture"), dict) and "input_modalities" in raw["architecture"])
        or isinstance(raw.get("pricing"), dict)
    )


def _has_llama_server_meta(raw: dict[str, Any]) -> bool:
    """Detect a llama-server /models entry (meta.n_ctx / n_ctx_train, or capabilities)."""
    meta = raw.get("meta")
    if isinstance(meta, dict) and (
        isinstance(meta.get("n_ctx"), int) or isinstance(meta.get("n_ctx_train"), int)
    ):
        return True
    return isinstance(raw.get("capabilities"), list)


def _normalize_openrouter_architecture(arch: Any) -> dict[str, Any]:
    """Keep only the architecture keys the stored schema defines; {} when empty."""
    if not isinstance(arch, dict):
        return {}
    out: dict[str, Any] = {}
    for key in ("input_modalities", "output_modalities"):
        if arch.get(key):
            out[key] = list(arch[key])
    for key in ("tokenizer", "instruct_type"):
        if arch.get(key):
            out[key] = arch[key]
    return out


def _normalize_openrouter(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize an OpenRouter /models entry into the STORED form."""
    out: dict[str, Any] = {}
    if isinstance(raw.get("context_length"), int):
        out["context_length"] = raw["context_length"]

    # top_provider.max_completion_tokens -> flat (stored canonical location).
    tp = raw.get("top_provider")
    if isinstance(tp, dict):
        if isinstance(tp.get("max_completion_tokens"), int):
            out["max_completion_tokens"] = tp["max_completion_tokens"]
        if "is_moderated" in tp:
            out["is_moderated"] = bool(tp["is_moderated"])

    arch = _normalize_openrouter_architecture(raw.get("architecture"))
    if arch:
        out["architecture"] = arch

    if isinstance(raw.get("supported_parameters"), list):
        params = list(raw["supported_parameters"])
        out["supported_parameters"] = params
        # WHY: upstream advertises reasoning SUPPORT inside supported_parameters
        # ("reasoning" / "reasoning_effort") and never a list of effort levels,
        # so only reasoning.supported is derivable here; effort_levels and
        # default_effort stay operator policy (models.yaml reasoning_effort).
        if {"reasoning", "reasoning_effort"} & {str(x).lower() for x in params}:
            out["reasoning"] = {"supported": True}

    pricing = raw.get("pricing")
    if isinstance(pricing, dict):
        new_pricing: dict[str, float] = {}
        for key in PRICING_KEYS:
            if pricing.get(key) is not None:
                new_pricing[key] = _parse_price(pricing[key])
        if new_pricing:
            out["pricing"] = new_pricing

    if raw.get("name"):
        out["name"] = raw["name"]
    if raw.get("description"):
        out["description"] = raw["description"]
    return out


def _native_caps_for(raw: dict[str, Any], native_models: list[Any]) -> list[str] | None:
    """Find the capabilities array a llama-server native ``models`` entry
    carries for ``raw`` — keyed by the entry's id, then name.

    Native entries name their model via "model", "name" or "id"; the
    OpenAI-compatible ``data`` entry is matched by its own id/name.
    """
    if not isinstance(native_models, list):
        return None
    by_key: dict[str, list[str]] = {}
    for n in native_models:
        if isinstance(n, dict) and isinstance(n.get("capabilities"), list):
            for key in ("model", "name", "id"):
                if n.get(key):
                    by_key[n[key]] = n["capabilities"]
    return by_key.get(raw.get("id")) or by_key.get(raw.get("name"))


def _normalize_llama_server(
    raw: dict[str, Any],
    native_models: list[Any] | None = None,
) -> dict[str, Any]:
    """Normalize a llama-server /models entry into the STORED form.

    Reads context from meta.n_ctx (the runtime window) falling back to
    n_ctx_train, and detects vision from the ``capabilities`` array (llama-server
    lists "multimodal" when an mmproj is loaded). When the entry itself carries
    no capabilities, the parallel native ``models`` array of the same response
    (``native_models``) is consulted — that array is where llama-server
    actually exposes multimodality; the OpenAI-compatible ``data`` entry has
    meta.n_ctx but not capabilities. The non-standard /props endpoint
    (modalities.video/audio) is not scraped — /models is enough.
    """
    out: dict[str, Any] = {}
    meta = raw.get("meta") or {}
    n_ctx = meta.get("n_ctx")
    if isinstance(n_ctx, int):
        out["context_length"] = n_ctx
    elif isinstance(meta.get("n_ctx_train"), int):
        out["context_length"] = meta["n_ctx_train"]

    caps = raw.get("capabilities")
    if caps is None and native_models:
        caps = _native_caps_for(raw, native_models)
    if isinstance(caps, list) and "multimodal" in {str(c).lower() for c in caps}:
        out["architecture"] = {
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
        }
    return out


def normalize_provider_model(
    raw: dict[str, Any],
    native_models: list[Any] | None = None,
) -> dict[str, Any]:
    """Normalize a raw upstream /models entry into the STORED schema.

    Dispatches on response SHAPE (not provider name) so any OpenAI-compatible
    backend is handled: OpenRouter (rich), llama-server (meta.n_ctx +
    capabilities.multimodal -> vision), or generic OpenAI (only
    id/object/owned_by -> empty, e.g. deepseek/kimi).

    ``native_models`` is the llama-server native ``models`` array from the same
    upstream response; the llama branch merges its capabilities in here.

    Upstream 'reasoning'/'reasoning_effort' in supported_parameters IS
    translated into ``reasoning: {"supported": True}`. Only that flag is
    derivable: no upstream shape carries the effort enum or default_enabled,
    which stay manual (model_info.yaml) or derived from the models.yaml
    reasoning_effort policy.
    """
    if not isinstance(raw, dict):
        return {}
    if _is_openrouter_shape(raw):
        return _normalize_openrouter(raw)
    if _has_llama_server_meta(raw):
        return _normalize_llama_server(raw, native_models)
    if native_models and _native_caps_for(raw, native_models) is not None:
        return _normalize_llama_server(raw, native_models)
    return {}
