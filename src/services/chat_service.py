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
from .chat.validator import ChatRequestValidator
from .chat.smart_buffer_manager import SmartStreamBufferManager
from .chat.format_processor import StreamFormatProcessor
from .chat.error_handler import StreamingErrorHandler
from .chat.logger import ChatLogger
from .chat.streaming_handler import StreamingHandler


class ChatService:
    """Координация компонентов обработки чат-запросов"""
    
    def __init__(self, config_manager: ConfigManager, httpx_client: httpx.AsyncClient, model_service: ModelService):
        self.config_manager = config_manager
        self.httpx_client = httpx_client
        self.model_service = model_service
        
        # Инициализация компонентов
        self.validator = ChatRequestValidator(config_manager)
        self.buffer_manager = SmartStreamBufferManager()
        self.format_processor = StreamFormatProcessor()
        self.error_handler = StreamingErrorHandler()
        self.logger = ChatLogger()
        self.streaming_handler = StreamingHandler(
            self.buffer_manager,
            self.format_processor,
            self.error_handler,
            self.logger
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
        self.logger.log_request(request_id, user_id, requested_model, request_body)

        # Валидация
        model_config, provider_name, provider_model_name, provider_config = \
            self.validator.validate_request(
                requested_model, allowed_models, api_key, project_name, request_id, user_id
            )

        # Получение провайдера
        try:
            provider_instance = get_provider_instance(provider_config.get("type"), provider_config, self.httpx_client)
        except ValueError as e:
            error_detail = {"error": {"message": f"Provider configuration error: {e}", "code": "provider_config_error"}}
            self.logger.log_error(Exception(f"Provider configuration error: {e}"), request_id, user_id, requested_model)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail,
            )
        
        try:
            response_data = await provider_instance.chat_completions(request_body, provider_model_name, model_config)
            
            if isinstance(response_data, StreamingResponse):
                return StreamingResponse(
                    self.streaming_handler.handle_stream(
                        response_data, provider_config.get("type"), requested_model, request_id, user_id
                    ), 
                    media_type=response_data.media_type
                )
            else:
                self.logger.log_response(request_id, user_id, requested_model, response_data)
                return JSONResponse(content=response_data)
            
        except HTTPException as e:
            self.logger.log_error(e, request_id, user_id, requested_model)
            raise e
        except Exception as e:
            self.logger.log_error(e, request_id, user_id, requested_model)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": {"message": f"An unexpected error occurred: {e}", "code": "unexpected_error"}},
            )