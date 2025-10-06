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

This service integrates with the StatisticsCollector and StreamProcessor to provide
unified handling of both streaming and non-streaming chat completion requests.
"""

import httpx
from typing import Dict, Any, Tuple
from fastapi import HTTPException, status, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.core.config_manager import ConfigManager
from src.providers import get_provider_instance
from src.services.model_service import ModelService
from src.core.exceptions import ProviderStreamError, ProviderNetworkError
from src.logging.config import logger
from .statistics_collector import StatisticsCollector
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
        
        # Unified processor instead of 4 separate components
        self.stream_processor = StreamProcessor()
    
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

        # Логирование запроса
        logger.info(
            "Chat Completion Request",
            extra={
                "log_type": "request",
                "request_id": request_id,
                "user_id": user_id,
                "model_id": requested_model,
                "request_body_summary": {
                    "model": requested_model,
                    "messages_count": len(request_body.get("messages", [])),
                    "first_message_content": request_body.get("messages", [{}])[0].get("content") if request_body.get("messages") else None
                }
            }
        )

        # Валидация
        if not requested_model:
            error_detail = {"error": {"message": "Model not specified in request", "code": "model_not_specified"}}
            logger.error(
                "Model not specified in request",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "log_type": "error",
                    "detail": error_detail
                }
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_detail,
            )

        if allowed_models and requested_model not in allowed_models:
            error_detail = {"error": {"message": f"Model '{requested_model}' is not available for your account", "code": "model_not_allowed"}}
            logger.error(
                f"Model '{requested_model}' is not available for user {user_id}",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": requested_model,
                    "log_type": "error",
                    "detail": error_detail
                }
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=error_detail,
            )

        # Прямое извлечение конфигурации
        current_config = self.config_manager.get_config()
        models = current_config.get("models", {})
        model_config = models.get(requested_model)
        
        if not model_config:
            error_detail = {"error": {"message": f"Model '{requested_model}' not found in configuration", "code": "model_not_found"}}
            logger.error(
                f"Model '{requested_model}' not found in configuration",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": requested_model,
                    "log_type": "error",
                    "detail": error_detail
                }
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail,
            )

        # Получение конфигурации провайдера
        provider_name = model_config.get("provider")
        provider_model_name = model_config.get("provider_model_name", requested_model)
        provider_config = current_config.get("providers", {}).get(provider_name)
        
        if not provider_config:
            error_detail = {"error": {"message": f"Provider '{provider_name}' for model '{requested_model}' not found in configuration", "code": "provider_not_found"}}
            logger.error(
                f"Provider '{provider_name}' for model '{requested_model}' not found in configuration",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": requested_model,
                    "log_type": "error",
                    "detail": error_detail
                }
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail,
            )

        # Получение провайдера
        try:
            provider_instance = get_provider_instance(provider_config.get("type"), provider_config, self.httpx_client)
        except ValueError as e:
            error_detail = {"error": {"message": f"Provider configuration error: {e}", "code": "provider_config_error"}}
            logger.error(
                f"Provider configuration error: {e}",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": requested_model,
                    "log_type": "error",
                    "detail": error_detail
                }
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail,
            )
        
        try:
            # Начинаем отсчет времени для всего запроса
            statistics = StatisticsCollector()
            statistics.start_timing()
            
            response_data = await provider_instance.chat_completions(request_body, provider_model_name, model_config)
            
            if isinstance(response_data, StreamingResponse):
                # Отмечаем завершение обработки промпта для стриминга
                # Оцениваем токены промпта на основе входных сообщений
                estimated_prompt_tokens = self._estimate_prompt_tokens(request_body)
                statistics.mark_prompt_complete(estimated_prompt_tokens)
                
                # Используем новый упрощенный процессор
                return StreamingResponse(
                    self.stream_processor.process_stream(
                        response_data.body_iterator, requested_model, request_id, user_id
                    ),
                    media_type=response_data.media_type
                )
            else:
                # Отмечаем завершение обработки промпта для нестримингового ответа
                usage = response_data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                statistics.mark_prompt_complete(prompt_tokens)
                statistics.mark_completion_complete(completion_tokens)
                
                # Получаем полную статистику
                full_statistics = statistics.get_statistics()
                
                # Обновляем ответ с расширенной статистикой
                enhanced_response = response_data.copy()
                if "usage" not in enhanced_response:
                    enhanced_response["usage"] = {}
                
                # Добавляем timing метрики к существующему usage
                enhanced_response["usage"].update(full_statistics)
                
                logger.info(
                    "Chat Completion Response",
                    extra={
                        "log_type": "response",
                        "request_id": request_id,
                        "user_id": user_id,
                        "model_id": requested_model,
                        "http_status_code": status.HTTP_200_OK,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "statistics": full_statistics,
                        "response_body_summary": {
                            "finish_reason": response_data.get("choices", [{}])[0].get("finish_reason"),
                            "content_preview": response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        }
                    }
                )
                return JSONResponse(content=enhanced_response)
            
        except HTTPException as e:
            logger.error(
                f"HTTPException in chat_completions: {e.detail.get('error', {}).get('message', str(e))}",
                extra={
                    "status_code": e.status_code,
                    "detail": e.detail,
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": requested_model,
                    "log_type": "error"
                }
            )
            raise e
        except Exception as e:
            logger.error(
                f"Unexpected error in chat_completions: {e}",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": requested_model,
                    "log_type": "error"
                },
                exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": {"message": f"Internal server error: {e}", "code": "internal_server_error"}},
            )
    
    def _estimate_prompt_tokens(self, request_body: Dict[str, Any]) -> int:
        """
        Приблизительная оценка количества токенов в промпте
        На основе содержимого сообщений
        
        Args:
            request_body: Тело запроса с сообщениями
            
        Returns:
            int: Приблизительное количество токенов в промпте
        """
        messages = request_body.get("messages", [])
        if not messages:
            return 0
        
        total_text = ""
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, str):
                total_text += content + " "
            elif isinstance(content, list):
                # Обработка мультимодального контента
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        total_text += item.get("text", "") + " "
        
        # Используем ту же логику оценки, что и в StreamProcessor
        words = len(total_text.split())
        chars = len(total_text)
        estimated_tokens = max(words, chars // 4)
        return estimated_tokens