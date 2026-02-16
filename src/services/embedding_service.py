import httpx
from typing import Dict, Any, Tuple

from fastapi import HTTPException, status, Request
from fastapi.responses import JSONResponse

from ..core.config_manager import ConfigManager
from ..core.logging import logger
from ..core.error_handling import ErrorHandler, ErrorContext
from .base import BaseService


class EmbeddingService(BaseService):
    """
    Service for handling embedding creation requests.
    
    This service manages the complete lifecycle of embedding requests including:
    - Authentication and authorization validation
    - Model validation and configuration lookup
    - Provider selection and instantiation
    - Request forwarding and response handling
    - Error handling and comprehensive logging
    
    Refactoring Phase 2: This service now inherits from BaseService to eliminate
    duplicate code for validation, provider instantiation, and logging.
    """
    
    def __init__(self, config_manager: ConfigManager, httpx_client: httpx.AsyncClient):
        """
        Initialize EmbeddingService.
        
        Args:
            config_manager: Configuration manager instance for accessing
                model and provider configurations
            httpx_client: Async HTTP client for making external requests
                to AI providers
        """
        super().__init__(config_manager, httpx_client)

    async def create_embeddings(self, request: Request, auth_data: Tuple[str, str, list, list]) -> Any:
        """
        Create embeddings for the given input text.
        
        This method handles embedding creation requests with comprehensive validation,
        error handling, and logging. It performs the following steps:
        1. Request validation and authentication
        2. Model configuration lookup
        3. Provider selection and instantiation
        4. Request forwarding to provider
        5. Response processing and logging
        
        Args:
            request: FastAPI request object containing the embedding request data
            auth_data: Authentication data tuple containing:
                - project_name (str): Name of the project making the request
                - api_key (str): API key for authentication
                - allowed_models (list): List of model IDs allowed for this API key
                - allowed_endpoints (list): List of endpoints allowed for this API key
        
        Returns:
            JSONResponse: JSON response with the embedding data and usage statistics
            
        Raises:
            HTTPException: With appropriate status codes for various error scenarios:
                - 400: Model not specified in request
                - 403: Model not allowed for this API key
                - 404: Model or provider not found in configuration
                - 500: Provider configuration error or internal server error
        """
        # Extract request context using base class method
        context_dict = self._get_request_context(request, auth_data)
        request_id = context_dict["request_id"]
        user_id = context_dict["user_id"]
        
        request_body = await request.json()
        requested_model = request_body.get("model")
        
        # Create error context for validation
        context = ErrorContext(
            request_id=request_id,
            user_id=user_id,
            model_id=requested_model
        )

        # DEBUG логирование полного запроса
        self._log_service_data(
            title="Embedding Request JSON",
            data=request_body,
            request_id=request_id,
            component="embedding_service",
            data_flow="incoming"
        )

        logger.request(
            operation="Embedding Creation Request",
            request_id=request_id,
            user_id=user_id,
            model_id=requested_model
        )

        # Validate and get configuration using base class method
        model_config, provider_name, provider_model_name, provider_config = \
            self._validate_and_get_config(requested_model, auth_data, context)

        # Get provider instance using base class method
        provider_instance = self._get_provider(provider_config, context)
        
        try:
            response_data = await provider_instance.embeddings(request_body, provider_model_name, model_config)
            
            # DEBUG логирование ответа от провайдера
            self._log_service_data(
                title="Embedding Response JSON",
                data=response_data,
                request_id=request_id,
                component="embedding_service",
                data_flow="from_provider"
            )
            
            # Log the response
            logger.response(
                operation="Embedding Creation Response",
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
            # Re-raise HTTPExceptions from our error handler (already logged)
            raise e
        except Exception as e:
            raise ErrorHandler.handle_internal_server_error(str(e), context, e)
