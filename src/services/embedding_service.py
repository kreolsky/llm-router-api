"""Embedding creation service proxying requests to configured providers."""
import httpx
from typing import Dict, Any, Tuple

from fastapi import HTTPException, status, Request
from fastapi.responses import JSONResponse

from ..core.config_manager import ConfigManager
from ..core.logging import logger
from ..core.error_handling import ErrorType, create_error
from .base import BaseService


class EmbeddingService(BaseService):
    """Proxies embedding requests to the configured provider."""

    def __init__(self, config_manager: ConfigManager, httpx_client: httpx.AsyncClient):
        super().__init__(config_manager, httpx_client)

    async def create_embeddings(self, request: Request, auth_data: Tuple[str, str, list, list]) -> Any:
        """Validate, dispatch, and return an embedding creation request."""
        context_dict = self._get_request_context(request, auth_data)
        request_id = context_dict["request_id"]
        user_id = context_dict["user_id"]
        
        request_body = await request.json()
        requested_model = request_body.get("model")
        
        error_ctx = dict(request_id=request_id, user_id=user_id, model_id=requested_model)

        self._log_service_data(
            title="Embedding Request JSON",
            data=request_body,
            request_id=request_id,
            component="embedding_service",
            data_flow="incoming"
        )

        logger.info(
            f"Request: Embedding Creation | model={requested_model}",
            request_id=request_id,
            user_id=user_id,
            model_id=requested_model
        )

        model_config, provider_name, provider_model_name, provider_config = \
            self._validate_and_get_config(requested_model, auth_data, **error_ctx)

        provider_instance = self._get_provider(provider_config, **error_ctx)
        
        try:
            response_data = await provider_instance.embeddings(request_body, provider_model_name, model_config)
            
            self._log_service_data(
                title="Embedding Response JSON",
                data=response_data,
                request_id=request_id,
                component="embedding_service",
                data_flow="from_provider"
            )
            
            logger.info(
                f"Response: Embedding Creation | model={requested_model}",
                request_id=request_id,
                user_id=user_id,
                model_id=requested_model,
                token_usage={
                    "prompt_tokens": response_data.get("usage", {}).get("prompt_tokens", 0),
                    "total_tokens": response_data.get("usage", {}).get("total_tokens", 0)
                }
            )
            return JSONResponse(content=response_data)
            
        except HTTPException as e:
            raise e
        except Exception as e:
            raise create_error(ErrorType.INTERNAL_SERVER_ERROR, original_exception=e, error_details=str(e), **error_ctx)
