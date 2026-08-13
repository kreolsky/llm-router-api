"""Model listing and detail retrieval with merged capability data.

ARCH: the hot path (/v1/models, /v1/models/{id}) reads capabilities from an
in-memory merged store and NEVER touches the network. Capability data is
sourced from two layers (see src/core/model_capabilities.py):

  1. the auto-cache (CapabilitiesCache, refreshed by a background task);
  2. config/model_info.yaml (manual override).

INVARIANT: model_info.yaml ALWAYS wins over the auto-cache.
"""
import time
from typing import Dict, Any, Tuple, Optional

from ..core.logging import logger
from ..core.error_handling import ErrorType, create_error
from ..core.model_capabilities import (
    CapabilitiesCache,
    merge_capabilities,
    refresh_provider_capabilities,
    render_capabilities,
)
from .base import BaseService


class ModelService(BaseService):
    """Lists models and retrieves single-model details from merged capabilities."""

    def __init__(self, config_manager, capabilities_cache: Optional[CapabilitiesCache] = None):
        super().__init__(config_manager)
        self.capabilities_cache = capabilities_cache

    def _build_model_response(self, model_id: str, **extra_fields) -> Dict[str, Any]:
        """Build a standardized model response object."""
        return {
            "id": model_id,
            "object": "model",
            "created": int(time.time()),
            "owned_by": "nnp-llm-router",
            "parent": None,
            "permission": [{
                "id": f"model-perm-{model_id}",
                "object": "model_permission",
                "created": int(time.time()),
                "allow_create_engine": False,
                "allow_sampling": True,
                "allow_logprobs": False,
                "allow_search_indices": False,
                "allow_view": True,
                "allow_fine_tuning": False,
                "organization": "*",
                "group": None,
                "is_blocking": False
            }],
            "root": model_id,
            **extra_fields
        }

    def _resolve_stored_capabilities(self, model_id: str) -> Dict[str, Any]:
        """Merge the auto-cache and manual model_info into the STORED form.

        INVARIANT: model_info.yaml always wins over the auto-cache (deep merge
        where lists are replaced, not concatenated).
        """
        cache_data: Dict[str, Any] = {}
        if self.capabilities_cache is not None:
            cache_data = self.capabilities_cache.get(model_id) or {}
        model_info = self.config_manager.get_config().get("model_info", {}).get(model_id) or {}
        return merge_capabilities(cache_data, model_info)

    def _capability_meta(self, model_id: str) -> Dict[str, Any]:
        """Provenance fields (source, fetched_at) for diagnostics, when available."""
        if self.capabilities_cache is None:
            return {}
        meta = self.capabilities_cache.get_meta(model_id)
        if meta is None:
            return {}
        return {
            "capabilities_source": meta.get("source"),
            "capabilities_fetched_at": meta.get("fetched_at"),
        }

    async def list_models(self, auth_data: Tuple[str, str, list, list]) -> Dict[str, Any]:
        """Return OpenAI-compatible model list filtered by allowed_models and is_hidden.

        Capability fields are rendered identically to retrieve_model, so the
        list and the detail endpoint never diverge.
        """
        _, _, allowed_models, _ = auth_data
        current_config = self.config_manager.get_config()
        models_config = current_config.get("models", {})

        models_list = []
        for model_id, model_data in models_config.items():
            if model_data.get("is_hidden", False):
                continue

            if not allowed_models or model_id in allowed_models:
                stored = self._resolve_stored_capabilities(model_id)
                rendered = render_capabilities(stored)
                models_list.append(self._build_model_response(model_id, **rendered))
        return {"object": "list", "data": models_list}

    async def retrieve_model(
        self,
        model_id: str,
        auth_data: Tuple[str, str, list, list],
        refresh: bool = False,
    ) -> Dict[str, Any]:
        """Return model details from merged capabilities (no live upstream call).

        The hot path reads only from the in-memory store. ``refresh=True``
        (debug) triggers a best-effort background refresh of the model's
        provider before reading; failures are non-fatal (stale-if-error).
        """
        _, _, allowed_models, _ = auth_data
        # INVARIANT: access check BEFORE existence to prevent information leakage.
        if allowed_models and model_id not in allowed_models:
            raise create_error(ErrorType.MODEL_NOT_ALLOWED, model_id=model_id)

        current_config = self.config_manager.get_config()
        models_config = current_config.get("models", {})

        model_data = models_config.get(model_id)
        if not model_data:
            raise create_error(ErrorType.MODEL_NOT_FOUND, model_id=model_id)

        provider_name = model_data.get("provider")
        provider_model_name = model_data.get("provider_model_name")

        provider_config = current_config.get("providers", {}).get(provider_name)
        if not provider_config:
            raise create_error(ErrorType.PROVIDER_NOT_FOUND, model_id=model_id, provider_name=provider_name)

        # ARCH: optional debug refresh — NOT the default path. Best effort,
        # errors swallowed (stale-if-error). The result is still read from cache.
        if (
            refresh
            and self.capabilities_cache is not None
            and self.config_manager.model_cache_enabled
        ):
            try:
                await refresh_provider_capabilities(self.config_manager, self.capabilities_cache, provider_name)
            except Exception as e:
                logger.warning(
                    f"Debug capabilities refresh failed for {model_id}: {e}",
                    error_type="capabilities_refresh_error",
                )

        stored = self._resolve_stored_capabilities(model_id)
        rendered = render_capabilities(stored)
        meta = self._capability_meta(model_id)

        return self._build_model_response(
            model_id,
            provider=provider_name,
            provider_model_name=provider_model_name,
            params=model_data.get("params"),
            options=model_data.get("options"),
            **rendered,
            **meta,
        )
