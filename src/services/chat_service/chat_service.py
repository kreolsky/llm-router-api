"""
Chat Service Module

This module provides the main ChatService class that coordinates chat completion
requests, including model validation, provider selection, and response handling.

The ChatService is the central orchestrator for chat completion operations in the
NNP LLM Router system. It handles the complete lifecycle of chat requests including:
- Authentication and authorization validation
- Model configuration and provider selection
- Request forwarding to appropriate providers
- Response processing (both streaming and non-streaming)
- Error handling and comprehensive logging
- Performance statistics collection

This service integrates with the StreamProcessor to provide
unified handling of both streaming and non-streaming chat completion requests
with complete transparent proxying.
"""

import httpx
from typing import Dict, Any, Tuple
from fastapi import HTTPException, status, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ...core.config_manager import ConfigManager
from ...services.model_service import ModelService
from ...core.logging import logger
from ...core.sanitizer import MessageSanitizer
from ...core.error_handling import ErrorHandler, ErrorContext
from ...services.base import BaseService
from .stream_processor import StreamProcessor


class ChatService(BaseService):
    """
    Main service for coordinating chat completion requests.
    
    This service handles the complete lifecycle of chat completion requests:
    - Authentication and authorization validation
    - Model validation and configuration lookup
    - Provider selection and instantiation
    - Request forwarding and response handling
    - Streaming and non-streaming response processing
    - Error handling and comprehensive logging
    - Performance statistics collection and reporting
    
    The service acts as a facade that coordinates between various components
    including configuration management, model services, provider instances,
    and stream processing utilities.
    
    Attributes:
        config_manager (ConfigManager): Configuration manager instance for
            accessing model and provider configurations
        httpx_client (httpx.AsyncClient): HTTP client for making external
            requests to AI providers
        model_service (ModelService): Model service for model-related operations
            and validations
        stream_processor (StreamProcessor): Stream processor for handling
            streaming responses from providers
    """
    
    def __init__(self, config_manager: ConfigManager, httpx_client: httpx.AsyncClient, model_service: ModelService):
        """
        Initialize ChatService.
        
        Args:
            config_manager: Configuration manager instance for accessing
                model and provider configurations
            httpx_client: Async HTTP client for making external requests
                to AI providers
            model_service: Model service for model-related operations
                and validations
        """
        # Initialize base service with config_manager and httpx_client
        super().__init__(config_manager, httpx_client)
        self.model_service = model_service
        
        # Создаем StreamProcessor с конфигурацией для поддержки санитизации
        self.stream_processor = StreamProcessor(config_manager)
    
    async def chat_completions(self, request: Request, auth_data: Tuple[str, str, list, list]) -> Any:
        """
        Main method for processing chat completion requests.
        
        This method handles both streaming and non-streaming chat completion
        requests with comprehensive validation, error handling, and logging.
        It performs the following steps:
        1. Request validation and authentication
        2. Model configuration lookup
        3. Provider selection and instantiation
        4. Request forwarding to provider
        5. Response processing (streaming or non-streaming)
        6. Statistics collection and logging
        
        Args:
            request: FastAPI request object containing the chat completion
                request data in JSON format
            auth_data: Authentication data tuple containing:
                - project_name (str): Name of the project making the request
                - api_key (str): API key for authentication
                - allowed_models (list): List of model IDs allowed for this API key
            
        Returns:
            StreamingResponse: For streaming requests, returns a streaming
                response with SSE-formatted chunks
            JSONResponse: For non-streaming requests, returns a JSON response
                with the completion data and statistics
                
        Raises:
            HTTPException: With appropriate status codes for various error scenarios:
                - 400: Model not specified in request
                - 403: Model not allowed for this API key
                - 404: Model not found in configuration
                - 500: Provider configuration error or internal server error
        """
        # Extract request context using base class method
        context_dict = self._get_request_context(request, auth_data)
        request_id = context_dict["request_id"]
        user_id = context_dict["user_id"]

        request_body = await request.json()
        requested_model = request_body.get("model")

        # DEBUG логирование полного запроса
        self._log_service_data(
            title="Chat Completion Request JSON",
            data=request_body,
            request_id=request_id,
            component="chat_service",
            data_flow="incoming"
        )

        # Логирование запроса
        logger.request(
            operation="Chat Completion Request",
            request_id=request_id,
            user_id=user_id,
            model_id=requested_model
        )

        # Create error context for validation
        context = ErrorContext(
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
            # Use the simple request context manager
            with logger.request_context(
                operation="Chat Completion",
                request_id=request_id,
                user_id=user_id,
                model_id=requested_model,
                provider_name=provider_name
            ):
                # Sanitize request messages if enabled
                if self.config_manager.should_sanitize_messages:
                    messages = request_body.get("messages", [])
                    if messages:
                        original_count = len(messages)
                        sanitized_messages = MessageSanitizer.sanitize_messages(messages, enabled=True)
                        request_body["messages"] = sanitized_messages
                        
                        if len(sanitized_messages) != original_count:
                            logger.info(
                                f"Sanitized {original_count} messages to {len(sanitized_messages)}",
                                request_id=request_id,
                                user_id=user_id
                            )
                
                response_data = await provider_instance.chat_completions(request_body, provider_model_name, model_config)
                
                # DEBUG логирование ответа от провайдера
                if isinstance(response_data, StreamingResponse):
                    self._log_service_data(
                        title="Streaming Response Started",
                        data={
                            "streaming": True,
                            "model": requested_model,
                            "request_id": request_id
                        },
                        request_id=request_id,
                        component="chat_service",
                        data_flow="from_provider"
                    )
                    
                    return StreamingResponse(
                        self.stream_processor.process_stream(
                            response_data.body_iterator, requested_model, request_id, user_id
                        ),
                        media_type=response_data.media_type,
                        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
                    )
                else:
                    # Для нестриминговых ответов логируем полный JSON
                    self._log_service_data(
                        title="Chat Completion Response JSON",
                        data=response_data,
                        request_id=request_id,
                        component="chat_service",
                        data_flow="from_provider"
                    )
                    
                    return JSONResponse(content=response_data)
            
        except HTTPException as e:
            # Re-raise HTTPExceptions from our error handler (already logged)
            raise e
        except Exception as e:
            raise ErrorHandler.handle_internal_server_error(str(e), context, e)