"""
Управление буферами стриминга и UTF-8 обработкой
"""
import codecs
from typing import List


class StreamBufferManager:
    """Управление буферами стриминга и UTF-8 обработкой"""
    
    def __init__(self, max_buffer_size: int = 1024 * 1024):
        """
        Инициализация менеджера буферов
        
        Args:
            max_buffer_size: Максимальный размер буфера в байтах
        """
        self.max_buffer_size = max_buffer_size
        self.utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='ignore')
        self.sse_buffer = ""
        self.json_buffer = ""
    
    def process_chunk(self, chunk: bytes) -> str:
        """
        Обрабатывает новый чанк и возвращает декодированную строку
        
        Args:
            chunk: Новый чанк данных
            
        Returns:
            Декодированная строка
        """
        # Используем incremental decoder для обработки UTF-8 границ
        decoded_chunk = self.utf8_decoder.decode(chunk, final=False)
        
        # Если decoded_chunk пустой, значит чанк был частью многобайтного символа
        if not decoded_chunk:
            return ""
        
        return decoded_chunk
    
    def get_sse_events(self) -> List[str]:
        """
        Возвращает полные SSE события из буфера
        
        Returns:
            Список полных SSE событий
        """
        events = []
        
        # SSE события разделены двойным переносом строки
        while '\n\n' in self.sse_buffer:
            event, self.sse_buffer = self.sse_buffer.split('\n\n', 1)
            if event.strip():
                events.append(event)
        
        return events
    
    def get_json_lines(self) -> List[str]:
        """
        Возвращает полные JSON строки из буфера
        
        Returns:
            Список полных JSON строк
        """
        lines = self.json_buffer.split('\n')
        self.json_buffer = lines[-1]  # Сохраняем неполную строку
        
        return [line for line in lines[:-1] if line.strip()]
    
    def add_to_sse_buffer(self, data: str):
        """
        Добавляет данные в SSE буфер с проверкой переполнения
        
        Args:
            data: Данные для добавления
        """
        if len(self.sse_buffer) + len(data) > self.max_buffer_size:
            # Очищаем половину буфера при переполнении
            self.sse_buffer = self.sse_buffer[len(self.sse_buffer)//2:]
        
        self.sse_buffer += data
    
    def add_to_json_buffer(self, data: str):
        """
        Добавляет данные в JSON буфер с проверкой переполнения
        
        Args:
            data: Данные для добавления
        """
        if len(self.json_buffer) + len(data) > self.max_buffer_size:
            # Очищаем половину буфера при переполнении
            self.json_buffer = self.json_buffer[len(self.json_buffer)//2:]
        
        self.json_buffer += data
    
    def clear_buffers(self):
        """Очищает все буферы"""
        self.sse_buffer = ""
        self.json_buffer = ""
        # Сбрасываем декодер
        self.utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='ignore')
    
    def get_remaining_data(self) -> tuple:
        """
        Возвращает оставшиеся данные в буферах
        
        Returns:
            Tuple[sse_buffer, json_buffer]
        """
        return self.sse_buffer, self.json_buffer