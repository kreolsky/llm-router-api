"""
Валидация чат-запросов и проверка прав доступа
"""
from typing import Dict, Any, Tuple
from fastapi import HTTPException, status

from ...core.config_manager import ConfigManager
from ...logging.config import logger


class ChatRequestValidator:
    """Валидация чат-запросов и проверка прав доступа"""
    
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
    
    def validate_request(
        self, 
        requested_model: str, 
        allowed_models: list, 
        api_key: str, 
        project_name: str,
        request_id: str,
        user_id: str
    ) -> Tuple[Dict[str, Any], str, str, Dict[str, Any]]:
        """
        Валидирует запрос и возвращает конфигурацию модели
        
        Args:
            requested_model: Запрошенная модель
            allowed_models: Список разрешенных моделей
            api_key: API ключ
            project_name: Имя проекта
            request_id: ID запроса
            user_id: ID пользователя
            
        Returns:
            Tuple[model_config, provider_name, provider_model_name, provider_config]
            
        Raises:
            HTTPException: При ошибках валидации
        """
        # Валидация наличия модели
        if not requested_model:
            error_detail = {"error": {"message": "Model not specified in request", "code": "model_not_specified"}}
            logger.error("Model not specified in request", extra={
                "detail": error_detail, 
                "request_id": request_id, 
                "user_id": user_id, 
                "log_type": "error"
            })
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_detail,
            )

        # Проверка доступа к модели
        if allowed_models and requested_model not in allowed_models:
            error_detail = {"error": {"message": f"Model '{requested_model}' not allowed for this API key", "code": "model_not_allowed"}}
            logger.error(f"Model '{requested_model}' not allowed for API key", extra={
                "detail": error_detail, 
                "api_key": api_key, 
                "project_name": project_name, 
                "request_id": request_id, 
                "user_id": user_id, 
                "log_type": "error"
            })
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=error_detail,
            )

        # Получение конфигурации модели
        current_config = self.config_manager.get_config()
        models = current_config.get("models", {})
        model_config = models.get(requested_model)
        
        if not model_config:
            error_detail = {"error": {"message": f"Model '{requested_model}' not found in configuration", "code": "model_not_found"}}
            logger.error(f"Model '{requested_model}' not found in configuration", extra={
                "detail": error_detail, 
                "request_id": request_id, 
                "user_id": user_id, 
                "log_type": "error"
            })
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
            logger.error(f"Provider '{provider_name}' for model '{requested_model}' not found", extra={
                "detail": error_detail, 
                "request_id": request_id, 
                "user_id": user_id, 
                "log_type": "error"
            })
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=error_detail,
            )
            
        return model_config, provider_name, provider_model_name, provider_config