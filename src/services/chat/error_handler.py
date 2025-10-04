"""
Обработка ошибок стриминга
"""
import json
from typing import Optional
from fastapi import status

from ...core.exceptions import ProviderStreamError, ProviderNetworkError


class StreamingErrorHandler:
    """
    Форматирование ошибок стриминга БЕЗ логирования
    (Логирование выполняется в StreamingHandler)
    """
    
    def format_sse_error(self, message: str, code: str, status_code: int) -> bytes:
        """Форматирует ошибку в SSE формате"""
        error_payload = {
            "error": {
                "message": message,
                "type": "api_error",
                "code": code,
                "param": None
            }
        }
        return f"data: {json.dumps(error_payload)}\n\n".encode('utf-8')
    
    def format_streaming_error(self, error: Exception) -> bytes:
        """
        Форматирует ошибку стриминга БЕЗ логирования
        
        Args:
            error: Исключение
            
        Returns:
            Отформатированная ошибка в SSE формате
        """
        if isinstance(error, ProviderStreamError):
            return self.format_sse_error(
                error.message,
                error.error_code,
                error.status_code
            )
        elif isinstance(error, ProviderNetworkError):
            return self.format_sse_error(
                error.message,
                "provider_network_error",
                status.HTTP_503_SERVICE_UNAVAILABLE
            )
        else:
            return self.format_sse_error(
                f"An unexpected error occurred during streaming: {error}",
                "unexpected_streaming_error",
                status.HTTP_500_INTERNAL_SERVER_ERROR
            )