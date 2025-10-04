from typing import Literal
import json

class StreamFormatDetector:
    """
    Единый источник истины для определения формата стрима
    """
    
    @staticmethod
    def detect(event: str) -> Literal['sse', 'ndjson']:
        """
        Определяет формат события стрима
        
        Args:
            event: Строка события
            
        Returns:
            'sse' или 'ndjson'
        """
        event_stripped = event.strip()
        
        # SSE события содержат 'data:' или начинаются с ':'
        if 'data:' in event_stripped or event_stripped.startswith(':'):
            return 'sse'
        
        # Пробуем распарсить как JSON для NDJSON
        try:
            json.loads(event_stripped)
            return 'ndjson'
        except json.JSONDecodeError:
            # По умолчанию SSE (более распространенный формат)
            return 'sse'
    
    @staticmethod
    def is_sse(event: str) -> bool:
        """Проверка на SSE формат"""
        return StreamFormatDetector.detect(event) == 'sse'
    
    @staticmethod
    def is_ndjson(event: str) -> bool:
        """Проверка на NDJSON формат"""
        return StreamFormatDetector.detect(event) == 'ndjson'