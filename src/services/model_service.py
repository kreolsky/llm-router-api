import httpx
import os
import time
import logging
from typing import Dict, Any

from fastapi import HTTPException, status

from ..core.config_manager import ConfigManager
from ..logging.config import logger # Import logger from logging_config

class ModelService:
    def __init__(self, config_manager: ConfigManager, httpx_client: httpx.AsyncClient):
        self.config_manager = config_manager
        self.httpx_client = httpx_client

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
            provider_base_url = provider_config.get("base_url")
            provider_api_key_env = provider_config.get("api_key_env")
            provider_api_key = os.getenv(provider_api_key_env)

            if not provider_base_url or not provider_api_key:
                logger.warning(f"Missing base_url or API key for provider {provider_name}")
            else:
                provider_models_list_url = f"{provider_base_url}/models"
                headers = {
                    "Authorization": f"Bearer {provider_api_key}",
                    "Content-Type": "application/json"
                }
                if "headers" in provider_config:
                    headers.update(provider_config["headers"])

                provider_response = await client.get(provider_models_list_url, headers=headers)
                provider_response.raise_for_status()
                provider_models_data = provider_response.json()
                    
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

    async def list_models(self) -> Dict[str, Any]:
        current_config = self.config_manager.get_config()
        models_config = current_config.get("models", {})
        
        models_list = []
        for model_id, model_data in models_config.items():
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

    async def retrieve_model(self, model_id: str) -> Dict[str, Any]:
        current_config = self.config_manager.get_config()
        models_config = current_config.get("models", {})
        
        model_data = models_config.get(model_id)
        if not model_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": {"message": f"Model '{model_id}' not found", "code": "model_not_found"}},
            )
        
        provider_name = model_data.get("provider")
        provider_model_name = model_data.get("provider_model_name")

        provider_config = current_config.get("providers", {}).get(provider_name)
        if not provider_config:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": {"message": f"Provider '{provider_name}' not found for model '{model_id}'", "code": "provider_not_found"}},
            )

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
