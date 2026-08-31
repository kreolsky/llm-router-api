"""Model capabilities: serialization, upstream normalization, and auto-cache.

Two layers feed the /v1/models responses:

1. MANUAL layer — ``config/model_info.yaml`` (operator-curated, stored schema).
2. AUTO-CACHE layer — ``CapabilitiesCache``, populated from upstream ``/models``
   responses by a background task and persisted to ``data/model_cache.json``.

ARCH: the hot path (/v1/models, /v1/models/{id}) NEVER touches the network.
Capabilities are read from the in-memory merged store. Only the background
refresh task (and the optional ``?refresh=true`` debug flag) go upstream.

INVARIANT: model_info.yaml ALWAYS wins over the auto-cache, and lists are
*replaced* (not concatenated) — unlike ``utils.deep_merge``.
Why: two layers writing one shape with different merge semantics would make
the manual layer's overrides depend on list order instead of operator intent;
a manual ``input_modalities`` override must not be duplicated by the cache.
Both layers store the SAME normalized shape, so the merge is well-defined.

Split by concern: ``render.py`` (stored -> response + merge),
``normalizers.py`` (raw upstream -> stored), ``cache.py`` (the store),
``refresh.py`` (background orchestration).
"""
# SYSTEM: model-capabilities — manual layer + auto-cache + render
from .cache import CapabilitiesCache
from .normalizers import normalize_provider_model
from .refresh import capabilities_refresh_loop, refresh_all_capabilities, refresh_provider_capabilities
from .render import merge_capabilities, render_capabilities

__all__ = [
    "CapabilitiesCache",
    "capabilities_refresh_loop",
    "merge_capabilities",
    "normalize_provider_model",
    "refresh_all_capabilities",
    "refresh_provider_capabilities",
    "render_capabilities",
]
