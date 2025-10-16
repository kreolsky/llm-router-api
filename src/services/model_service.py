import httpx
import os
import time
from typing import Dict, Any, Tuple

from fastapi import HTTPException, status

from ..core.config_manager import ConfigManager
from ..logging.config import logger
from ..core.error_handling import ErrorHandler, ErrorContext

class ModelService:
    def __init__(self, config_manager: ConfigManager, httpx_client: httpx.AsyncClient):
        self.config_manager = config_manager
        self.httpx_client = httpx_client

    async def _get_provider_api_details(self, provider_config: Dict[str, Any]) -> Tuple[str, str, Dict[str, str]]:
        """Extracts base URL, API key, and headers for a given provider."""
        provider_base_url = provider_config.get("base_url")
        provider_api_key_env = provider_config.get("api_key_env")
        provider_api_key = os.getenv(provider_api_key_env) if provider_api_key_env else None

        if not provider_base_url:
            logger.warning(f"Missing base_url for provider {provider_config.get('name', 'unknown')}")
            return None, None, {}

        headers = {
            "Content-Type": "application/json"
        }
        if provider_api_key:
            headers["Authorization"] = f"Bearer {provider_api_key}"
        if "headers" in provider_config:
            headers.update(provider_config["headers"])
        return provider_base_url, provider_api_key, headers

    async def _fetch_provider_models(self, base_url: str, headers: Dict[str, str], client: httpx.AsyncClient) -> Dict[str, Any]:
        """Fetches models list from a provider's API."""
        provider_models_list_url = f"{base_url}/models"
        response = await client.get(provider_models_list_url, headers=headers)
        response.raise_for_status()
        return response.json()

    async def _get_model_details_from_provider(self, model_id: str, current_config: Dict[str, Any], client: httpx.AsyncClient) -> Dict[str, Any]:
        model_data = current_config.get("models", {}).get(model_id)
        if not model_data:
            return {}

        provider_name = model_data.get("provider")
        provider_model_name = model_data.get("provider_model_name")

        provider_config = current_config.get("providers", {}).get(provider_name)
        if not provider_config:
            return {}

        additional_model_details = {}
        try:
            base_url, api_key, headers = await self._get_provider_api_details(provider_config)
            if not base_url or not api_key:
                return {}

            provider_models_data = await self._fetch_provider_models(base_url, headers, client)
                    
            found_provider_model = None
            for p_model in provider_models_data.get("data", []):
                if p_model.get("id") == provider_model_name:
                    found_provider_model = p_model
                    break
            
            if found_provider_model:
                additional_model_details["description"] = found_provider_model.get("description")
                additional_model_details["context_length"] = found_provider_model.get("context_length")
                additional_model_details["architecture"] = found_provider_model.get("architecture")
                additional_model_details["pricing"] = found_provider_model.get("pricing")
            else:
                logger.warning(f"Provider model '{provider_model_name}' not found in provider's model list for {provider_name}")

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching model details from provider {provider_name}: {e.response.status_code} - {e.response.text}", extra={"error_message": e.response.text, "error_code": f"provider_http_error_{e.response.status_code}"}, exc_info=True)
        except httpx.RequestError as e:
            logger.error(f"Network error fetching model details from provider {provider_name}: {e}", extra={"error_message": str(e), "error_code": "provider_network_error"}, exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error fetching model details from provider {provider_name}: {e}", extra={"error_message": str(e), "error_code": "unexpected_error"}, exc_info=True)
        
        return additional_model_details

    async def list_models(self, auth_data: Tuple[str, str, list, list]) -> Dict[str, Any]:
        _, _, allowed_models, _ = auth_data
        current_config = self.config_manager.get_config()
        models_config = current_config.get("models", {})
        
        models_list = []
        for model_id, model_data in models_config.items():
            # If is_hidden is true, skip this model
            if model_data.get("is_hidden", False):
                continue

            if allowed_models is None or len(allowed_models) == 0 or model_id in allowed_models:
                models_list.append({
                    "id": model_id,
                    "object": "model",
                    "created": int(time.time()), # Placeholder
                    "owned_by": "nnp-llm-router", # Custom owner
                    "parent": None,
                    "permission": [
                        {
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
                        }
                    ],
                    "root": model_id
                })
        return {"object": "list", "data": models_list}

    async def retrieve_model(self, model_id: str, auth_data: Tuple[str, str, list, list]) -> Dict[str, Any]:
        _, _, allowed_models, _ = auth_data

        # Check if the model is allowed for this user
        if allowed_models and model_id not in allowed_models:
            context = ErrorContext(model_id=model_id)
            raise ErrorHandler.handle_model_not_allowed(model_id, context)

        current_config = self.config_manager.get_config()
        models_config = current_config.get("models", {})

        model_data = models_config.get(model_id)
        if not model_data:
            context = ErrorContext(model_id=model_id)
            raise ErrorHandler.handle_model_not_found(model_id, context)

        provider_name = model_data.get("provider")
        provider_model_name = model_data.get("provider_model_name")

        provider_config = current_config.get("providers", {}).get(provider_name)
        if not provider_config:
            context = ErrorContext(model_id=model_id, provider_name=provider_name)
            raise ErrorHandler.handle_provider_not_found(provider_name, model_id, context)

        # Dynamically fetch additional model details from the provider
        additional_model_details = await self._get_model_details_from_provider(model_id, current_config, self.httpx_client)

        response_data = {
            "id": model_id,
            "object": "model",
            "created": int(time.time()), # Placeholder
            "owned_by": "nnp-llm-router", # Custom owner
            "parent": None,
            "permission": [
                {
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
                }
            ],
            "root": model_id,
            "provider": provider_name,
            "provider_model_name": provider_model_name,
            "params": model_data.get("params"),
            "options": model_data.get("options"),
            **additional_model_details # Merge dynamically fetched details
        }
        return response_data
