import httpx
from typing import Dict, Any, Tuple

from fastapi import HTTPException, status, Request
from fastapi.responses import JSONResponse

from ..core.config_manager import ConfigManager
from ..providers import get_provider_instance
from ..core.logging import logger, RequestLogger, DebugLogger
from ..core.error_handling import ErrorHandler, ErrorContext

class EmbeddingService:
    def __init__(self, config_manager: ConfigManager, httpx_client: httpx.AsyncClient):
        self.config_manager = config_manager
        self.httpx_client = httpx_client

    async def create_embeddings(self, request: Request, auth_data: Tuple[str, str, list, list]) -> Any:
        project_name, api_key, allowed_models, _ = auth_data
        request_id = request.state.request_id
        user_id = project_name # Using project_name as user_id

        current_config = self.config_manager.get_config()
        
        request_body = await request.json()
        requested_model = request_body.get("model")
        
        # Create error context for validation
        context = ErrorContext(
            request_id=request_id,
            user_id=user_id,
            model_id=requested_model
        )

        # DEBUG логирование полного запроса
        DebugLogger.log_data_flow(
            logger=logger,
            title="DEBUG: Embedding Request JSON",
            data=request_body,
            data_flow="incoming",
            component="embedding_service",
            request_id=request_id
        )

        RequestLogger.log_request(
            logger=logger,
            operation="Embedding Creation Request",
            request_id=request_id,
            user_id=user_id,
            model_id=requested_model,
            request_data=request_body
        )

        if not requested_model:
            raise ErrorHandler.handle_model_not_specified(context)

        # For embeddings, we assume a single provider will handle all requests
        # The model specified in the request will be used to find the provider configuration
        # and the provider_model_name will be passed to the provider's embeddings method.
        
        # Check if the model is allowed for this user
        if allowed_models and requested_model not in allowed_models:
            raise ErrorHandler.handle_model_not_allowed(requested_model, context)
        
        # Find the model configuration
        model_config = current_config.get("models", {}).get(requested_model)
        if not model_config:
            raise ErrorHandler.handle_model_not_found(requested_model, context)

        provider_name = model_config.get("provider")
        provider_model_name = model_config.get("provider_model_name", requested_model)

        provider_config = current_config.get("providers", {}).get(provider_name)
        if not provider_config:
            raise ErrorHandler.handle_provider_not_found(provider_name, requested_model, context)

        try:
            provider_instance = get_provider_instance(provider_config.get("type"), provider_config, self.httpx_client)
        except ValueError as e:
            raise ErrorHandler.handle_provider_config_error(str(e), context, e)
        
        try:
            response_data = await provider_instance.embeddings(request_body, provider_model_name, model_config)
            
            # DEBUG логирование ответа от провайдера
            DebugLogger.log_data_flow(
                logger=logger,
                title="DEBUG: Embedding Response JSON",
                data=response_data,
                data_flow="from_provider",
                component="embedding_service",
                request_id=request_id
            )
            
            # Log the response
            RequestLogger.log_response(
                logger=logger,
                operation="Embedding Creation Response",
                request_id=request_id,
                user_id=user_id,
                model_id=requested_model,
                response_data=response_data,
                token_usage={
                    "prompt_tokens": response_data.get("usage", {}).get("prompt_tokens", 0),
                    "total_tokens": response_data.get("usage", {}).get("total_tokens", 0)
                }
            )
            return JSONResponse(content=response_data)
            
        except HTTPException as e:
            # Re-raise HTTPExceptions from our error handler (already logged)
            raise e
        except Exception as e:
            raise ErrorHandler.handle_internal_server_error(str(e), context, e)
