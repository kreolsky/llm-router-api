import httpx
import json
from typing import Dict, Any, Tuple

from fastapi import HTTPException, status, Request
from fastapi.responses import JSONResponse

from ..core.config_manager import ConfigManager
from ..providers import get_provider_instance
from ..core.auth import get_api_key
from ..logging.config import logger

class EmbeddingService:
    def __init__(self, config_manager: ConfigManager, httpx_client: httpx.AsyncClient):
        self.config_manager = config_manager
        self.httpx_client = httpx_client

    async def create_embeddings(self, request: Request, auth_data: Tuple[str, str, list]) -> Any:
        project_name, api_key, allowed_models = auth_data
        request_id = request.state.request_id
        user_id = project_name # Using project_name as user_id

        current_config = self.config_manager.get_config()
        
        request_body = await request.json()
        requested_model = request_body.get("model")

        logger.info(
            "Embedding Creation Request",
            extra={
                "log_type": "request",
                "request_id": request_id,
                "user_id": user_id,
                "model_id": requested_model,
                "request_body_summary": {
                    "model": requested_model,
                    "input_type": type(request_body.get("input")).__name__,
                    "input_length": len(request_body.get("input")) if isinstance(request_body.get("input"), (list, str)) else None
                }
            }
        )

        if not requested_model:
            error_detail = {"error": {"message": "Model not specified in request", "code": "model_not_specified"}}
            logger.error("Model not specified in request", extra={"detail": error_detail, "request_id": request_id, "user_id": user_id, "log_type": "error"})
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_detail,
            )

        # For embeddings, we assume a single provider will handle all requests
        # The model specified in the request will be used to find the provider configuration
        # and the provider_model_name will be passed to the provider's embeddings method.
        
        # Find the model configuration
        model_config = current_config.get("models", {}).get(requested_model)
        if not model_config:
            error_detail = {"error": {"message": f"Model '{requested_model}' not found in configuration", "code": "model_not_found"}}
            logger.error(f"Model '{requested_model}' not found in configuration", extra={"detail": error_detail, "request_id": request_id, "user_id": user_id, "log_type": "error"})
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail,
            )

        provider_name = model_config.get("provider")
        provider_model_name = model_config.get("provider_model_name", requested_model)

        provider_config = current_config.get("providers", {}).get(provider_name)
        if not provider_config:
            error_detail = {"error": {"message": f"Provider '{provider_name}' for model '{requested_model}' not found in configuration", "code": "provider_not_found"}}
            logger.error(f"Provider '{provider_name}' for model '{requested_model}' not found", extra={"detail": error_detail, "request_id": request_id, "user_id": user_id, "log_type": "error"})
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail,
            )

        try:
            provider_instance = get_provider_instance(provider_config.get("type"), provider_config, self.httpx_client)
        except ValueError as e:
            error_detail = {"error": {"message": f"Provider configuration error: {e}", "code": "provider_config_error"}}
            logger.error(f"Provider configuration error: {e}", extra={"detail": error_detail, "request_id": request_id, "user_id": user_id, "log_type": "error"})
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail,
            )
        
        try:
            response_data = await provider_instance.embeddings(request_body, provider_model_name, model_config)
            
            # Log the response
            usage = response_data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            total_tokens = usage.get("total_tokens", 0)

            logger.info(
                "Embedding Creation Response",
                extra={
                    "log_type": "response",
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": requested_model,
                    "http_status_code": status.HTTP_200_OK,
                    "prompt_tokens": prompt_tokens,
                    "total_tokens": total_tokens,
                    "response_body_summary": {
                        "data_length": len(response_data.get("data", []))
                    }
                }
            )
            return JSONResponse(content=response_data)
            
        except HTTPException as e:
            logger.error(f"HTTPException from provider: {e.detail.get('error', {}).get('message', str(e))}", extra={"status_code": e.status_code, "detail": e.detail, "request_id": request_id, "user_id": user_id, "model_id": requested_model, "log_type": "error"})
            raise e
        except Exception as e:
            error_detail = {"error": {"message": f"An unexpected error occurred: {e}", "code": "unexpected_error"}}
            logger.error(f"An unexpected error occurred: {e}", extra={"detail": error_detail, "request_id": request_id, "user_id": user_id, "model_id": requested_model, "log_type": "error"}, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail,
            )
