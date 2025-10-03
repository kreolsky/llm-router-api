"""
Обработка ошибок стриминга
"""
import json
from typing import Dict, Any
from fastapi import status

from ...core.exceptions import ProviderStreamError, ProviderNetworkError
from ...logging.config import logger


class StreamingErrorHandler:
    """Обработка ошибок стриминга"""
    
    def format_sse_error(self, message: str, code: str, status_code: int) -> bytes:
        """
        Форматирует ошибку в SSE формате
        
        Args:
            message: Сообщение об ошибке
            code: Код ошибки
            status_code: HTTP статус код
            
        Returns:
            Отформатированная ошибка в SSE формате
        """
        error_payload = {
            "error": {
                "message": message,
                "type": "api_error",
                "code": code,
                "param": None
            }
        }
        return f"data: {json.dumps(error_payload)}\n\n".encode('utf-8')
    
    def handle_streaming_error(self, error: Exception, request_id: str, user_id: str) -> bytes:
        """
        Обрабатывает ошибку стриминга и возвращает форматированный ответ
        
        Args:
            error: Исключение
            request_id: ID запроса
            user_id: ID пользователя
            
        Returns:
            Отформатированная ошибка в SSE формате
        """
        if isinstance(error, ProviderStreamError):
            logger.error(
                f"ProviderStreamError in stream for request {request_id}: {error.message}", 
                extra={
                    "request_id": request_id, 
                    "user_id": user_id, 
                    "log_type": "error", 
                    "status_code": error.status_code, 
                    "error_code": error.error_code, 
                    "original_exception": str(error.original_exception)
                }
            )
            return self.format_sse_error(error.message, error.error_code, error.status_code)
            
        elif isinstance(error, ProviderNetworkError):
            logger.error(
                f"ProviderNetworkError in stream for request {request_id}: {error.message}", 
                extra={
                    "request_id": request_id, 
                    "user_id": user_id, 
                    "log_type": "error", 
                    "original_exception": str(error.original_exception)
                }
            )
            return self.format_sse_error(error.message, "provider_network_error", status.HTTP_503_SERVICE_UNAVAILABLE)
            
        else:
            logger.error(
                f"Unexpected error in stream for request {request_id}: {error}", 
                extra={
                    "request_id": request_id, 
                    "user_id": user_id, 
                    "log_type": "error", 
                    "exception": str(error)
                }, 
                exc_info=True
            )
            return self.format_sse_error(
                f"An unexpected error occurred during streaming: {error}", 
                "unexpected_streaming_error", 
                status.HTTP_500_INTERNAL_SERVER_ERROR
            )