"""
Умная буферизация стриминга с проверкой полноты чанков
"""
import codecs
import json
from typing import List, Optional, Dict, Any

from .parsed_event import ParsedStreamEvent
from .format_detector import StreamFormatDetector


class SmartStreamBufferManager:
    """
    Умный менеджер буферизации с парсингом JSON один раз
    """
    
    def __init__(self, max_buffer_size: int = 1024 * 1024):
        """
        Инициализация умного менеджера буферов
        
        Args:
            max_buffer_size: Максимальный размер буфера в байтах
        """
        self.max_buffer_size = max_buffer_size
        self.utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='strict')
        self.buffer = ""
        self.problematic_bytes = b""
        self.problematic_attempts = 0
        self.max_problematic_attempts = 3
    
    def process_chunk(self, chunk: bytes) -> List[ParsedStreamEvent]:
        """
        Обрабатывает чанк и возвращает список ParsedStreamEvent
        
        Args:
            chunk: Новый чанк данных
            
        Returns:
            Список ParsedStreamEvent с кешированным JSON
        """
        # Восстановление UTF-8 (без изменений)
        if self.problematic_bytes:
            chunk = self.problematic_bytes + chunk
            self.problematic_bytes = b""
        
        try:
            decoded_chunk = self.utf8_decoder.decode(chunk, final=False)
        except UnicodeDecodeError as e:
            decoded_chunk = self._recover_utf8_sequence(chunk, e)
        
        if not decoded_chunk:
            return []
        
        self.buffer += decoded_chunk
        
        # Проверяем переполнение
        if len(self.buffer) > self.max_buffer_size:
            self.buffer = self.buffer[len(self.buffer)//2:]
        
        # Извлекаем и парсим события
        return self._extract_and_parse_events()
    
    def _extract_and_parse_events(self) -> List[ParsedStreamEvent]:
        """
        Извлекает события и парсит JSON один раз
        
        Returns:
            Список ParsedStreamEvent с данными
        """
        # Определяем формат по первым данным в буфере
        stream_format = StreamFormatDetector.detect(self.buffer)
        
        if stream_format == 'sse':
            return self._extract_sse_events()
        else:
            return self._extract_ndjson_events()
    
    def _extract_sse_events(self) -> List[ParsedStreamEvent]:
        """
        Извлекает SSE события с парсингом JSON
        
        Returns:
            Список ParsedStreamEvent
        """
        events = []
        
        while '\n\n' in self.buffer:
            event_raw, self.buffer = self.buffer.split('\n\n', 1)
            
            # Создаем ParsedStreamEvent с парсингом
            parsed_event = self._parse_sse_event(event_raw)
            
            # Добавляем только валидные события
            if parsed_event.is_valid:
                events.append(parsed_event)
        
        return events
    
    def _parse_sse_event(self, event_raw: str) -> ParsedStreamEvent:
        """
        Парсит SSE событие один раз
        
        Args:
            event_raw: Сырое SSE событие
            
        Returns:
            ParsedStreamEvent с распарсенным JSON
        """
        if not event_raw.strip():
            return ParsedStreamEvent(
                raw=event_raw,
                format='sse',
                is_valid=False,
                error="Empty event"
            )
        
        # Парсим JSON из SSE
        for line in event_raw.split('\n'):
            line = line.strip()
            
            # Пропускаем комментарии
            if line.startswith(':'):
                continue
            
            if line.startswith('data: '):
                data_part = line[6:].strip()
                
                # [DONE] - валидное завершающее событие
                if data_part == '[DONE]':
                    return ParsedStreamEvent(
                        raw=event_raw,
                        format='sse',
                        data={'done': True},
                        is_valid=True
                    )
                
                # Парсим JSON
                try:
                    parsed_data = json.loads(data_part)
                    return ParsedStreamEvent(
                        raw=event_raw,
                        format='sse',
                        data=parsed_data,
                        is_valid=True
                    )
                except json.JSONDecodeError as e:
                    return ParsedStreamEvent(
                        raw=event_raw,
                        format='sse',
                        is_valid=False,
                        error=f"JSON parse error: {e}"
                    )
        
        # Пустые события или только комментарии - тоже валидны
        return ParsedStreamEvent(
            raw=event_raw,
            format='sse',
            is_valid=True
        )
    
    def _extract_ndjson_events(self) -> List[ParsedStreamEvent]:
        """
        Извлекает NDJSON события с парсингом JSON
        
        Returns:
            Список ParsedStreamEvent
        """
        events = []
        
        lines = self.buffer.split('\n')
        self.buffer = lines[-1]  # Сохраняем неполную строку
        
        for line in lines[:-1]:
            parsed_event = self._parse_ndjson_line(line)
            
            if parsed_event.is_valid:
                events.append(parsed_event)
        
        return events
    
    def _parse_ndjson_line(self, line: str) -> ParsedStreamEvent:
        """
        Парсит NDJSON строку один раз
        
        Args:
            line: NDJSON строка
            
        Returns:
            ParsedStreamEvent с распарсенным JSON
        """
        if not line.strip():
            return ParsedStreamEvent(
                raw=line,
                format='ndjson',
                is_valid=False,
                error="Empty line"
            )
        
        try:
            parsed_data = json.loads(line)
            return ParsedStreamEvent(
                raw=line,
                format='ndjson',
                data=parsed_data,
                is_valid=True
            )
        except json.JSONDecodeError as e:
            return ParsedStreamEvent(
                raw=line,
                format='ndjson',
                is_valid=False,
                error=f"JSON parse error: {e}"
            )
    
    def get_remaining_data(self) -> ParsedStreamEvent:
        """
        Возвращает оставшиеся данные как ParsedStreamEvent
        
        Returns:
            ParsedStreamEvent с оставшимися данными
        """
        if not self.buffer.strip():
            return ParsedStreamEvent(
                raw="",
                format='sse',
                is_valid=False
            )
        
        # Определяем формат оставшихся данных
        stream_format = StreamFormatDetector.detect(self.buffer)
        
        remaining = self.buffer
        self.buffer = ""
        
        # Парсим оставшиеся данные
        if stream_format == 'sse':
            return self._parse_sse_event(remaining)
        else:
            return self._parse_ndjson_line(remaining)
    
    def _recover_utf8_sequence(self, chunk: bytes, error: UnicodeDecodeError) -> str:
        """Восстановление UTF-8 (без изменений)"""
        self.problematic_attempts += 1
        
        if self.problematic_attempts >= self.max_problematic_attempts:
            result = chunk.decode('utf-8', errors='replace')
            self.problematic_bytes = b""
            self.problematic_attempts = 0
            return result
        
        error_pos = error.start
        valid_part = chunk[:error_pos]
        problematic_part = chunk[error_pos:]
        
        result = ""
        try:
            result = self.utf8_decoder.decode(valid_part, final=False)
        except UnicodeDecodeError:
            for byte in valid_part:
                try:
                    result += self.utf8_decoder.decode(bytes([byte]), final=False)
                except UnicodeDecodeError:
                    continue
        
        self.problematic_bytes = problematic_part
        return result
    
    def clear_buffers(self):
        """Очищает буфер и сбрасывает декодер"""
        self.buffer = ""
        self.utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='strict')
        self.problematic_bytes = b""
        self.problematic_attempts = 0