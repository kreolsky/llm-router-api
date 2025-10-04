"""
Обновленный ChatService после рефакторинга
"""
import httpx
from typing import Dict, Any, Tuple

from fastapi import HTTPException, status, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..core.config_manager import ConfigManager
from ..providers import get_provider_instance
from .model_service import ModelService
from .chat.smart_buffer_manager import SmartStreamBufferManager
from .chat.format_processor import StreamFormatProcessor
from .chat.error_handler import StreamingErrorHandler
from .chat.streaming_handler import StreamingHandler
from ..logging.config import logger


class ChatService:
    """Координация компонентов обработки чат-запросов"""
    
    def __init__(self, config_manager: ConfigManager, httpx_client: httpx.AsyncClient, model_service: ModelService):
        self.config_manager = config_manager
        self.httpx_client = httpx_client
        self.model_service = model_service
        
        # Инициализация компонентов
        self.buffer_manager = SmartStreamBufferManager()
        self.format_processor = StreamFormatProcessor()
        self.error_handler = StreamingErrorHandler()
        self.streaming_handler = StreamingHandler(
            self.buffer_manager,
            self.format_processor,
            self.error_handler
        )
    
    async def chat_completions(self, request: Request, auth_data: Tuple[str, str, list]) -> Any:
        """
        Основной метод обработки чат-запросов
        
        Args:
            request: FastAPI запрос
            auth_data: Данные аутентификации (project_name, api_key, allowed_models)
            
        Returns:
            StreamingResponse или JSONResponse
        """
        project_name, api_key, allowed_models = auth_data
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
            error_detail = {"error": {"message": f"Model '{requested_model}' not allowed for this API key", "code": "model_not_allowed"}}
            logger.error(
                f"Model '{requested_model}' not allowed for this API key",
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
            response_data = await provider_instance.chat_completions(request_body, provider_model_name, model_config)
            
            if isinstance(response_data, StreamingResponse):
                # Используем гибридный подход: формат из конфигурации или автоопределение
                stream_format = provider_config.get("stream_format")  # None если не указан
                
                return StreamingResponse(
                    self.streaming_handler.handle_stream(
                        response_data, provider_config.get("type"), requested_model, request_id, user_id, stream_format
                    ),
                    media_type=response_data.media_type
                )
            else:
                usage = response_data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)

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
                        "response_body_summary": {
                            "finish_reason": response_data.get("choices", [{}])[0].get("finish_reason"),
                            "content_preview": response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        }
                    }
                )
                return JSONResponse(content=response_data)
            
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
                f"An unexpected error occurred in chat_completions: {e}",
                extra={
                    "detail": {"error": {"message": f"An unexpected error occurred: {e}", "code": "unexpected_error"}},
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": requested_model,
                    "log_type": "error"
                },
                exc_info=True
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": {"message": f"An unexpected error occurred: {e}", "code": "unexpected_error"}},
            )