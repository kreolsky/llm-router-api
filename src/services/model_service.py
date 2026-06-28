"""Model listing and detail retrieval with dynamic provider enrichment."""
import time
from typing import Dict, Any, Tuple

from ..core.logging import logger
from ..core.error_handling import ErrorType, create_error
from .base import BaseService


class ModelService(BaseService):
    """Lists models and retrieves single-model details enriched from the provider."""

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

    async def list_models(self, auth_data: Tuple[str, str, list, list]) -> Dict[str, Any]:
        """Return OpenAI-compatible model list filtered by allowed_models and is_hidden."""
        _, _, allowed_models, _ = auth_data
        current_config = self.config_manager.get_config()
        models_config = current_config.get("models", {})
        model_info_config = current_config.get("model_info", {})
        
        models_list = []
        for model_id, model_data in models_config.items():
            if model_data.get("is_hidden", False):
                continue

            if not allowed_models or model_id in allowed_models:
                model_info = model_info_config.get(model_id) or {}
                models_list.append(self._build_model_response(model_id, **model_info))
        return {"object": "list", "data": models_list}

    async def _get_model_details_from_provider(
        self,
        provider_name: str,
        provider_config: Dict[str, Any],
        provider_model_name: str,
        request_id: str = "unknown"
    ) -> Dict[str, Any]:
        """Fetch live model metadata via the provider, returning {} on any error.

        # WHY: provider detail errors are non-fatal; the model response is valid without enrichment.
        """
        additional_model_details = {}
        try:
            provider_instance = await self._get_provider(provider_name, provider_config)
            found_model = await provider_instance.get_model(
                provider_model_name, request_id=request_id
            )
            if found_model:
                additional_model_details["description"] = found_model.get("description")
                additional_model_details["context_length"] = found_model.get("context_length")
                additional_model_details["architecture"] = found_model.get("architecture")
                additional_model_details["pricing"] = found_model.get("pricing")
            else:
                logger.warning(
                    f"Provider model '{provider_model_name}' not found in provider's model list for {provider_name}",
                    provider_name=provider_name,
                    provider_model_name=provider_model_name,
                    error_type="model_not_found_in_provider_list"
                )
        except Exception as e:
            logger.error(
                f"Error fetching model details from provider {provider_name}: {e}",
                provider_name=provider_name,
                error_message=str(e),
                error_type="provider_model_detail_error",
                request_id=request_id,
                exc_info=True
            )
        return additional_model_details

    async def retrieve_model(self, model_id: str, auth_data: Tuple[str, str, list, list]) -> Dict[str, Any]:
        """Return model details enriched with live provider metadata."""
        _, _, allowed_models, _ = auth_data
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

        model_info_config = current_config.get("model_info", {})
        model_info = model_info_config.get(model_id) or {}

        additional_model_details = await self._get_model_details_from_provider(
            provider_name, provider_config, provider_model_name
        )

        merged_details = {**additional_model_details, **model_info}

        return self._build_model_response(
            model_id,
            provider=provider_name,
            provider_model_name=provider_model_name,
            params=model_data.get("params"),
            options=model_data.get("options"),
            **merged_details
        )
