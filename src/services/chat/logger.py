"""
Логирование чат-операций
"""
from typing import Dict, Any
from fastapi import HTTPException, status

from ...logging.config import logger


class ChatLogger:
    """Логирование всех чат-операций"""
    
    def log_request(self, request_id: str, user_id: str, model_id: str, request_body: Dict[str, Any]):
        """
        Логирует входящий запрос
        
        Args:
            request_id: ID запроса
            user_id: ID пользователя
            model_id: ID модели
            request_body: Тело запроса
        """
        logger.info(
            "Chat Completion Request",
            extra={
                "log_type": "request",
                "request_id": request_id,
                "user_id": user_id,
                "model_id": model_id,
                "request_body_summary": {
                    "model": model_id,
                    "messages_count": len(request_body.get("messages", [])),
                    "first_message_content": request_body.get("messages", [{}])[0].get("content") if request_body.get("messages") else None
                }
            }
        )
    
    def log_response(self, request_id: str, user_id: str, model_id: str, response_data: Dict[str, Any]):
        """
        Логирует ответ
        
        Args:
            request_id: ID запроса
            user_id: ID пользователя
            model_id: ID модели
            response_data: Данные ответа
        """
        usage = response_data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        logger.info(
            "Chat Completion Response",
            extra={
                "log_type": "response",
                "request_id": request_id,
                "user_id": user_id,
                "model_id": model_id,
                "http_status_code": status.HTTP_200_OK,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "response_body_summary": {
                    "finish_reason": response_data.get("choices", [{}])[0].get("finish_reason"),
                    "content_preview": response_data.get("choices", [{}])[0].get("message", {}).get("content", "")
                }
            }
        )
    
    def log_streaming_completion(self, request_id: str, user_id: str, model_id: str, 
                               content: str, usage: Dict[str, Any]):
        """
        Логирует завершение стриминга
        
        Args:
            request_id: ID запроса
            user_id: ID пользователя
            model_id: ID модели
            content: Полный контент
            usage: Данные об использовании
        """
        prompt_tokens = usage.get("prompt_tokens", 0) if usage else 0
        completion_tokens = usage.get("completion_tokens", 0) if usage else 0

        logger.info(
            "Chat Completion Response",
            extra={
                "log_type": "response",
                "request_id": request_id,
                "user_id": user_id,
                "model_id": model_id,
                "http_status_code": status.HTTP_200_OK,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "response_body_summary": {
                    "finish_reason": "stop",
                    "content_preview": content
                }
            }
        )
    
    def log_error(self, error: Exception, request_id: str, user_id: str, model_id: str):
        """
        Логирует ошибку
        
        Args:
            error: Исключение
            request_id: ID запроса
            user_id: ID пользователя
            model_id: ID модели
        """
        if isinstance(error, HTTPException):
            logger.error(
                f"HTTPException from provider: {error.detail.get('error', {}).get('message', str(error))}",
                extra={
                    "status_code": error.status_code,
                    "detail": error.detail,
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": model_id,
                    "log_type": "error"
                }
            )
        else:
            logger.error(
                f"An unexpected error occurred: {error}",
                extra={
                    "detail": {"error": {"message": f"An unexpected error occurred: {error}", "code": "unexpected_error"}},
                    "request_id": request_id,
                    "user_id": user_id,
                    "model_id": model_id,
                    "log_type": "error"
                },
                exc_info=True
            )