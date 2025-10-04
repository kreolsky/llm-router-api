from dataclasses import dataclass
from typing import Optional, Dict, Any, Literal

@dataclass
class ParsedStreamEvent:
    """
    Событие стрима с кешированным распарсенным JSON
    
    Attributes:
        raw: Исходная строка события
        format: Формат события ('sse' или 'ndjson')
        data: Распарсенный JSON (None если парсинг не удался)
        is_valid: Флаг валидности события
        error: Ошибка парсинга (если есть)
    """
    raw: str
    format: Literal['sse', 'ndjson']
    data: Optional[Dict[str, Any]] = None
    is_valid: bool = True
    error: Optional[str] = None
    
    @property
    def is_done(self) -> bool:
        """Проверка на завершающее событие"""
        if self.format == 'sse':
            return 'data: [DONE]' in self.raw
        elif self.data:
            return self.data.get('done', False)
        return False
    
    @property
    def has_content(self) -> bool:
        """Есть ли контент в событии"""
        if not self.data:
            return False
        
        if self.format == 'sse':
            return 'choices' in self.data and \
                   self.data['choices'][0].get('delta', {}).get('content') is not None
        elif self.format == 'ndjson':
            return self.data.get('message', {}).get('content') is not None
        
        return False
    
    @property
    def content(self) -> str:
        """Извлекает контент из события"""
        if not self.data:
            return ""
        
        if self.format == 'sse':
            return self.data.get('choices', [{}])[0].get('delta', {}).get('content', '')
        elif self.format == 'ndjson':
            return self.data.get('message', {}).get('content', '')
        
        return ""
    
    @property
    def usage(self) -> Optional[Dict[str, Any]]:
        """Извлекает usage данные"""
        if not self.data:
            return None
        
        if self.format == 'sse':
            return self.data.get('usage')
        elif self.format == 'ndjson' and self.data.get('done'):
            if 'prompt_eval_count' in self.data:
                return {
                    "prompt_tokens": self.data.get("prompt_eval_count", 0),
                    "completion_tokens": self.data.get("eval_count", 0)
                }
            return self.data.get('usage')
        
        return None