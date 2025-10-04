"""
Умная буферизация стриминга с проверкой полноты чанков
"""
import codecs
import json
from typing import List


class SmartStreamBufferManager:
    """
    Умный менеджер буферизации, который проверяет полноту событий
    и отправляет только корректные данные
    """
    
    def __init__(self, max_buffer_size: int = 1024 * 1024):
        """
        Инициализация умного менеджера буферов
        
        Args:
            max_buffer_size: Максимальный размер буфера в байтах
        """
        self.max_buffer_size = max_buffer_size
        self.utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='ignore')
        self.buffer = ""
    
    def process_chunk(self, chunk: bytes) -> List[str]:
        """
        Обрабатывает чанк и возвращает список полных событий
        
        Args:
            chunk: Новый чанк данных
            
        Returns:
            Список полных SSE/NDJSON событий готовых к отправке
        """
        # Декодируем чанк
        decoded_chunk = self.utf8_decoder.decode(chunk, final=False)
        if not decoded_chunk:
            return []
        
        # Добавляем в буфер
        self.buffer += decoded_chunk
        
        # Проверяем переполнение буфера
        if len(self.buffer) > self.max_buffer_size:
            # Очищаем половину буфера при переполнении
            self.buffer = self.buffer[len(self.buffer)//2:]
        
        # Извлекаем полные события
        complete_events = self._extract_complete_events()
        
        return complete_events
    
    def _extract_complete_events(self) -> List[str]:
        """
        Извлекает полные события из буфера
        
        Returns:
            Список полных событий
        """
        events = []
        
        # Определяем формат и извлекаем события
        if self._is_sse_format():
            events = self._extract_sse_events()
        else:
            events = self._extract_ndjson_events()
        
        return events
    
    def _is_sse_format(self) -> bool:
        """
        Определяет формат данных в буфере
        
        Returns:
            True если SSE формат, False если NDJSON
        """
        return 'data:' in self.buffer or self.buffer.startswith(':')
    
    def _extract_sse_events(self) -> List[str]:
        """
        Извлекает полные SSE события из буфера
        
        Returns:
            Список полных SSE событий
        """
        events = []
        
        # SSE события разделены двойным переносом строки
        while '\n\n' in self.buffer:
            event, self.buffer = self.buffer.split('\n\n', 1)
            if self._is_valid_sse_event(event):
                events.append(event)
        
        return events
    
    def _extract_ndjson_events(self) -> List[str]:
        """
        Извлекает полные NDJSON события из буфера
        
        Returns:
            Список полных NDJSON строк
        """
        events = []
        
        # NDJSON строки разделены переносом строки
        lines = self.buffer.split('\n')
        self.buffer = lines[-1]  # Сохраняем последнюю неполную строку
        
        for line in lines[:-1]:
            if self._is_valid_ndjson_line(line):
                events.append(line)
        
        return events
    
    def _is_valid_sse_event(self, event: str) -> bool:
        """
        Проверяет валидность SSE события
        
        Args:
            event: SSE событие для проверки
            
        Returns:
            True если событие валидное
        """
        if not event.strip():
            return False
        
        for line in event.split('\n'):
            line = line.strip()
            if line.startswith(':'):
                continue  # Комментарии валидны
            
            if line.startswith('data: '):
                data_part = line[6:].strip()
                if data_part == '[DONE]':
                    return True
                
                try:
                    json.loads(data_part)
                    return True  # Если JSON парсится, считаем валидным
                except json.JSONDecodeError:
                    return False
        
        return True  # Пустые события или комментарии валидны
    
    def _is_valid_ndjson_line(self, line: str) -> bool:
        """
        Проверяет валидность NDJSON строки
        
        Args:
            line: NDJSON строка для проверки
            
        Returns:
            True если строка валидная
        """
        if not line.strip():
            return False
        
        try:
            json.loads(line)
            return True  # Если JSON парсится, считаем валидным
        except json.JSONDecodeError:
            return False
    
    def get_remaining_data(self) -> str:
        """
        Возвращает оставшиеся данные в буфере и очищает его
        
        Returns:
            Оставшиеся данные в буфере
        """
        remaining = self.buffer
        self.buffer = ""
        return remaining
    
    def clear_buffers(self):
        """Очищает буфер и сбрасывает декодер"""
        self.buffer = ""
        self.utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='ignore')