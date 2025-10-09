"""
Модуль санитизации сообщений от клиентской контаминации

Этот модуль предоставляет функциональность для очистки сообщений от 
нестандартных полей, которые могут вызывать ошибки у строгих провайдеров
таких как OpenRouter.
"""

import logging
from typing import Dict, Any, List

from src.logging.config import logger


class MessageSanitizer:
    """Класс для очистки сообщений от нестандартных полей"""
    
    # Список полей, которые нужно удалять из сообщений
    SERVICE_FIELDS = ['done', '__stream_end__', '__internal__', 'stream_end']
    
    @classmethod
    def sanitize_messages(cls, messages: List[Dict[str, Any]], enabled: bool = True) -> List[Dict[str, Any]]:
        """
        Очищает сообщения от служебных полей если санитизация включена
        
        Args:
            messages: Список сообщений для очистки
            enabled: Включена ли санитизация
            
        Returns:
            Очищенный список сообщений
        """
        if not enabled:
            logger.debug("Message sanitization is disabled")
            return messages
        
        logger.debug(f"Sanitizing {len(messages)} messages from client-side contamination")
        sanitized = []
        removed_fields_count = 0
        
        for i, message in enumerate(messages):
            clean_message = message.copy()
            removed_in_message = []
            
            # Удаляем известные служебные поля
            for field in cls.SERVICE_FIELDS:
                if field in clean_message:
                    removed_in_message.append(field)
                    clean_message.pop(field, None)
                    removed_fields_count += 1
            
            # Логируем удаленные поля для отладки
            if removed_in_message:
                logger.debug(f"Removed fields {removed_in_message} from message {i}")
            
            sanitized.append(clean_message)
        
        if removed_fields_count > 0:
            logger.info(f"Message sanitization removed {removed_fields_count} service fields from {len(messages)} messages")
        
        return sanitized