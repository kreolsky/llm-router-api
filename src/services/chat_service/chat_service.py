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
from ...providers import get_provider_instance
from ...services.model_service import ModelService
from ...core.logging import logger
from ...core.sanitizer import MessageSanitizer
from ...core.error_handling import ErrorHandler, ErrorContext
from .stream_processor import StreamProcessor


class ChatService:
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
        self.config_manager = config_manager
        self.httpx_client = httpx_client
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
        project_name, api_key, allowed_models, _ = auth_data
        request_id = request.state.request_id
        user_id = project_name

        request_body = await request.json()
        requested_model = request_body.get("model")

        # DEBUG логирование полного запроса
        logger.debug_data(
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
        
        # Валидация
        if not requested_model:
            raise ErrorHandler.handle_model_not_specified(context)

        if allowed_models and requested_model not in allowed_models:
            raise ErrorHandler.handle_model_not_allowed(requested_model, context)

        # Прямое извлечение конфигурации
        current_config = self.config_manager.get_config()
        models = current_config.get("models", {})
        model_config = models.get(requested_model)
        
        if not model_config:
            raise ErrorHandler.handle_model_not_found(requested_model, context)

        # Получение конфигурации провайдера
        provider_name = model_config.get("provider")
        provider_model_name = model_config.get("provider_model_name", requested_model)
        provider_config = current_config.get("providers", {}).get(provider_name)
        
        if not provider_config:
            raise ErrorHandler.handle_provider_not_found(provider_name, requested_model, context)

        # Получение провайдера
        try:
            provider_instance = get_provider_instance(provider_config.get("type"), provider_config, self.httpx_client)
        except ValueError as e:
            raise ErrorHandler.handle_provider_config_error(str(e), context, e)
        
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
                    logger.debug_data(
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
                        media_type=response_data.media_type
                    )
                else:
                    # Для нестриминговых ответов логируем полный JSON
                    logger.debug_data(
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