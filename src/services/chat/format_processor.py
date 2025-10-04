"""
Преобразование форматов стриминга (SSE/NDJSON)
"""
import json
import time
from typing import Dict, Any, Tuple

from .parsed_event import ParsedStreamEvent


class StreamFormatProcessor:
    """
    Обработка событий без повторного парсинга JSON
    """
    
    @staticmethod
    def detect_format(event: str) -> str:
        """
        Делегирует определение формата в StreamFormatDetector
        Оставлен для обратной совместимости
        """
        from .format_detector import StreamFormatDetector
        return StreamFormatDetector.detect(event)
    
    def process_parsed_event(self, event: ParsedStreamEvent,
                            full_content: str,
                            usage: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """
        Обрабатывает ParsedStreamEvent (JSON уже распарсен)
        
        Args:
            event: ParsedStreamEvent с готовым data
            full_content: Текущий полный контент
            usage: Текущие данные об использовании
            
        Returns:
            Tuple[updated_full_content, updated_usage]
        """
        # Используем готовый data вместо парсинга!
        if not event.data:
            return full_content, usage
        
        # Обработка ошибок
        if 'error' in event.data:
            return full_content, usage
        
        # Извлечение контента через свойство
        if event.has_content:
            full_content += event.content
        
        # Извлечение usage через свойство
        if event.usage:
            usage = event.usage
        
        return full_content, usage
    
    def format_ndjson_to_sse(self, event: ParsedStreamEvent,
                            model_id: str,
                            request_id: str) -> bytes:
        """
        Преобразует NDJSON ParsedStreamEvent в SSE формат
        
        Args:
            event: ParsedStreamEvent с NDJSON данными
            model_id: ID модели
            request_id: ID запроса
            
        Returns:
            SSE отформатированный чанк
        """
        if not event.data or event.data.get('done'):
            return b""
        
        # Используем готовый data!
        content = event.content
        
        if not content:
            return b""
        
        # Формируем OpenAI совместимый чанк
        openai_chunk = {
            "id": f"chatcmpl-{request_id}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model_id,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": content},
                    "logprobs": None,
                    "finish_reason": None
                }
            ]
        }
        
        return f"data: {json.dumps(openai_chunk)}\n\n".encode('utf-8')