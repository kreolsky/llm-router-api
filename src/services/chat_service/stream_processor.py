"""
Stream Processor Module

This module provides the StreamProcessor class for handling streaming responses
from various AI providers and converting them to standardized SSE format.

The StreamProcessor is a unified processor that replaces multiple previous
streaming components. It handles both SSE (Server-Sent Events) and NDJSON
(Newline Delimited JSON) formats from various providers including OpenAI,
Anthropic, Ollama, and others.

Key Features:
- Automatic format detection (SSE vs NDJSON)
- Buffer management for incomplete data chunks
- UTF-8 decoding with error handling
- Error handling and formatting for streaming responses
- Statistics collection integration
- Support for multiple provider-specific response formats
"""

import codecs
import json
import time
from typing import Dict, Any, AsyncGenerator, Optional, List

from src.logging.config import logger
from src.core.exceptions import ProviderStreamError, ProviderNetworkError
from .statistics_collector import StatisticsCollector


class StreamProcessor:
    """
    Unified processor for handling streaming responses from AI providers.
    
    This class replaces multiple previous streaming components with a single
    unified processor that handles both SSE and NDJSON formats from various
    providers (OpenAI, Anthropic, Ollama, etc.).
    
    The processor automatically detects the stream format, manages buffers for
    incomplete data chunks, handles UTF-8 decoding, and converts provider-specific
    formats to standardized SSE format for consistent client responses.
    
    Key Features:
    - Automatic format detection (SSE vs NDJSON)
    - Buffer management for incomplete data chunks
    - Error handling and formatting
    - Statistics collection integration
    - UTF-8 decoding with error handling
    - Support for multiple provider-specific response formats
    
    Attributes:
        max_buffer_size (int): Maximum buffer size in bytes (default: 1MB)
        utf8_decoder: Incremental UTF-8 decoder with error replacement
        buffer (str): Accumulated data buffer for incomplete events
        statistics (StatisticsCollector): Statistics collector instance
        content_length (int): Length of processed content in characters
    """
    
    def __init__(self, max_buffer_size: int = 1024 * 1024):
        """
        Initialize StreamProcessor.
        
        Args:
            max_buffer_size (int): Maximum buffer size in bytes to prevent
                memory exhaustion from malformed streams. Defaults to 1MB.
        """
        self.max_buffer_size = max_buffer_size
        self.utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        self.buffer = ""
        self.statistics = StatisticsCollector()
        self.content_length = 0
    
    async def process_stream(self,
                           provider_stream: AsyncGenerator[bytes, None],
                           model_id: str,
                           request_id: str,
                           user_id: str) -> AsyncGenerator[bytes, None]:
        """
        Main method for processing streaming responses.
        
        This method takes a raw provider stream and converts it to standardized
        SSE format while handling errors and collecting statistics. It processes
        the stream chunk by chunk, extracting events, and yielding formatted
        SSE responses.
        
        Args:
            provider_stream: Raw byte stream from the provider. This should be
                an async generator yielding bytes chunks.
            model_id: ID of the model being used for the request
            request_id: Unique identifier for the request for logging and tracking
            user_id: Identifier for the user making the request
            
        Yields:
            bytes: SSE-formatted chunks ready for HTTP streaming. Each chunk
                is properly formatted with "data: " prefix and double newline
                termination.
                
        Raises:
            ProviderStreamError: When stream processing encounters provider-specific errors
            ProviderNetworkError: When network issues occur during stream processing
            Exception: For unexpected errors during stream processing
        """
        logger.info("Starting stream processing", extra={
            "request_id": request_id,
            "user_id": user_id,
            "model": model_id
        })
        
        # Начинаем отсчет времени
        self.statistics.start_timing()
        
        full_content = ""
        stream_has_error = False
        first_token_received = False
        
        try:
            event_count = 0
            async for chunk in provider_stream:
                try:
                    # Декодируем и обрабатываем чанк
                    decoded_chunk = self.utf8_decoder.decode(chunk, final=False)
                    if decoded_chunk:
                        self.buffer += decoded_chunk
                        
                        # Обрабатываем события из буфера
                        events = self._extract_events()
                        for event_data in events:
                            event_count += 1
                            chunk_bytes = await self._process_event_data(
                                event_data, model_id, request_id, full_content
                            )
                            if chunk_bytes:
                                # Отмечаем получение первого токена
                                if not first_token_received:
                                    first_token_received = True
                                    # Оцениваем токены промпта (приблизительно)
                                    # ВАЖНО: full_content здесь еще пустой, поэтому используем 0
                                    self.statistics.mark_prompt_complete(0)
                                
                                yield chunk_bytes
                                # Обновляем контент для следующего события
                                full_content = self._extract_content(event_data, full_content)
                
                except Exception as e:
                    logger.error("Stream processing error", extra={
                        "request_id": request_id,
                        "user_id": user_id,
                        "error": str(e),
                        "error_type": type(e).__name__
                    }, exc_info=True)
                    
                    yield self._format_error(e)
                    stream_has_error = True
                    break
                    
        except Exception as e:
            logger.error("Critical stream error", extra={
                "request_id": request_id,
                "user_id": user_id,
                "error": str(e)
            }, exc_info=True)
            
            yield self._format_error(e)
            stream_has_error = True
        
        # Завершаем стрим если не было ошибок
        if not stream_has_error:
            # Обрабатываем оставшиеся данные в буфере
            if self.buffer.strip():
                events = self._extract_events(final=True)
                for event_data in events:
                    chunk_bytes = await self._process_event_data(
                        event_data, model_id, request_id, full_content
                    )
                    if chunk_bytes:
                        yield chunk_bytes
                        # Обновляем контент для оставшихся событий
                        full_content = self._extract_content(event_data, full_content)
            
            # Отмечаем завершение генерации и рассчитываем токены
            estimated_completion_tokens = self._estimate_tokens(full_content)
            self.statistics.mark_completion_complete(estimated_completion_tokens)
            
            # Отправляем финальное событие со статистикой
            statistics = self.statistics.get_statistics()
            if statistics:
                yield self._format_statistics_event(statistics, request_id, model_id)
            
            logger.info("Stream completed", extra={
                "request_id": request_id,
                "user_id": user_id,
                "model": model_id,
                "content_length": len(full_content),
                "statistics": statistics
            })
            
            yield b"data: [DONE]\n\n"
        
        # Очищаем буфер
        self._clear_buffer()
    
    def _extract_events(self, final: bool = False) -> List[Dict[str, Any]]:
        """
        Извлекает события из буфера
        
        Args:
            final: Флаг окончания стрима
            
        Returns:
            Список распарсенных событий
        """
        events = []
        
        if not self.buffer:
            return events
        
        # Определяем формат по первым данным
        stream_format = self._detect_format(self.buffer)
        
        if stream_format == 'sse':
            events = self._extract_sse_events(final)
        else:
            events = self._extract_ndjson_events(final)
        
        return events
    
    def _detect_format(self, event: str) -> str:
        """
        Определяет формат стрима
        
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
    
    def _extract_sse_events(self, final: bool) -> List[Dict[str, Any]]:
        """Извлекает SSE события"""
        events = []
        
        # Поддерживаем оба формата разделителей: \n\n и \r\n\r\n
        # Сначала пробуем найти любой из разделителей
        separator_positions = []
        
        # Ищем позиции всех возможных разделителей
        for separator in ['\r\n\r\n', '\n\n']:
            pos = self.buffer.find(separator)
            if pos != -1:
                separator_positions.append((pos, separator))
        
        # Сортируем по позиции (самый ранний разделитель)
        separator_positions.sort(key=lambda x: x[0])
        
        # Обрабатываем события пока есть разделители
        while separator_positions:
            pos, separator = separator_positions[0]
            event_raw = self.buffer[:pos]
            self.buffer = self.buffer[pos + len(separator):]
            
            event_data = self._parse_sse_event(event_raw)
            if event_data:
                events.append(event_data)
            
            # Обновляем позиции для оставшегося буфера
            separator_positions = []
            for sep in ['\r\n\r\n', '\n\n']:
                pos = self.buffer.find(sep)
                if pos != -1:
                    separator_positions.append((pos, sep))
            separator_positions.sort(key=lambda x: x[0])
        
        # Если final=True, обрабатываем оставшиеся данные
        if final and self.buffer.strip():
            event_data = self._parse_sse_event(self.buffer)
            if event_data:
                events.append(event_data)
            self.buffer = ""
        
        return events
    
    def _parse_sse_event(self, event_raw: str) -> Optional[Dict[str, Any]]:
        """Парсит SSE событие"""
        if not event_raw.strip():
            return None
        
        try:
            for line in event_raw.split('\n'):
                line = line.strip()
                
                # Пропускаем комментарии
                if line.startswith(':'):
                    continue
                
                if line.startswith('data: '):
                    data_part = line[6:].strip()
                    
                    # [DONE] - валидное завершающее событие
                    if data_part == '[DONE]':
                        return {'done': True}
                    
                    # Парсим JSON
                    try:
                        return json.loads(data_part)
                    except json.JSONDecodeError:
                        return None
            
            return None
        except Exception as e:
            logger.error(f"Error parsing SSE event: {e}", exc_info=True)
            return None
    
    def _extract_ndjson_events(self, final: bool) -> List[Dict[str, Any]]:
        """Извлекает NDJSON события"""
        events = []
        
        lines = self.buffer.split('\n')
        if not final:
            self.buffer = lines[-1]  # Сохраняем неполную строку
            lines = lines[:-1]
        else:
            self.buffer = ""
        
        for line in lines:
            if line.strip():
                try:
                    event_data = json.loads(line)
                    events.append(event_data)
                except json.JSONDecodeError:
                    continue
        
        return events
    
    async def _process_event_data(self,
                                event_data: Dict[str, Any],
                                model_id: str,
                                request_id: str,
                                full_content: str) -> Optional[bytes]:
        """
        Обрабатывает распарсенные данные события
        
        Args:
            event_data: Распарсенные данные события
            model_id: ID модели
            request_id: ID запроса
            full_content: Текущий полный контент
            
        Returns:
            SSE отформатированный чанк или None
        """
        if not event_data:
            return None
        
        # Обработка ошибок
        if 'error' in event_data:
            return self._format_error(Exception(event_data['error']))
        
        # Завершающее событие [DONE]
        if event_data.get('done'):
            return None
        
        # Проверяем на завершающее событие с finish_reason
        if 'choices' in event_data:
            choices = event_data.get('choices', [])
            if choices:
                choice = choices[0]
                finish_reason = choice.get('finish_reason')
                delta = choice.get('delta', {})
                
                # Если есть finish_reason и delta пустой - это завершающее событие
                if finish_reason and not delta.get('content'):
                    return None
            else:
                # Пустой список choices - пропускаем
                return None
        
        # Извлекаем контент
        content = self._extract_content_from_data(event_data)
        if not content:
            return None
        
        # Формируем SSE чанк
        return self._format_sse_chunk(content, model_id, request_id)
    
    def _extract_content(self, event_data: Dict[str, Any], current_content: str) -> str:
        """Извлекает контент и обновляет полный контент"""
        content = self._extract_content_from_data(event_data)
        return current_content + content if content else current_content
    
    def _extract_content_from_data(self, event_data: Dict[str, Any]) -> str:
        """Извлекает контент из распарсенных данных"""
        # SSE формат (OpenAI)
        if 'choices' in event_data:
            choices = event_data.get('choices', [])
            if not choices:
                return ""
            
            choice = choices[0]
            delta = choice.get('delta', {})
            
            # OpenAI формат: delta.content
            if 'content' in delta:
                return delta.get('content', '')
            
            # Ollama формат: delta с полями role, content, tool_calls
            if 'role' in delta and 'content' in delta:
                return delta.get('content', '')
        
        # NDJSON формат (Ollama)
        if 'message' in event_data:
            return event_data.get('message', {}).get('content', '')
        
        return ""
    
    def _format_sse_chunk(self, content: str, model_id: str, request_id: str) -> bytes:
        """Форматирует контент в SSE чанк"""
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
    
    def _format_error(self, error: Exception) -> bytes:
        """Форматирует ошибку в SSE формате"""
        if isinstance(error, ProviderStreamError):
            message = error.message
            code = error.error_code
        elif isinstance(error, ProviderNetworkError):
            message = error.message
            code = "provider_network_error"
        else:
            message = f"An unexpected error occurred during streaming: {error}"
            code = "unexpected_streaming_error"
        
        error_payload = {
            "error": {
                "message": message,
                "type": "api_error",
                "code": code,
                "param": None
            }
        }
        
        return f"data: {json.dumps(error_payload)}\n\n".encode('utf-8')
    
    def _clear_buffer(self):
        """Очищает буфер и сбрасывает декодер"""
        self.buffer = ""
        self.utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    
    def _estimate_tokens(self, text: str) -> int:
        """
        Приблизительная оценка количества токенов в тексте
        Использует эмпирическое правило: ~4 символа на токен для английского текста
        """
        if not text:
            return 0
        # Более точная оценка: учитываем пробелы и знаки препинания
        words = len(text.split())
        chars = len(text)
        # Комбинированная оценка: учитываем и слова, и символы
        estimated_tokens = max(words, chars // 4)
        return estimated_tokens
    
    def _format_statistics_event(self, statistics: Dict[str, Any], request_id: str, model_id: str) -> bytes:
        """Форматирует событие со статистикой в SSE формате"""
        # Форматируем статистику в ожидаемом формате
        statistics_event = {
            "prompt_tokens": statistics.get("prompt_tokens", 0),
            "prompt_time": statistics.get("prompt_time", 0),
            "prompt_tokens_per_sec": statistics.get("prompt_tokens_per_sec", 0),
            "completion_tokens": statistics.get("completion_tokens", 0),
            "completion_time": statistics.get("completion_time", 0),
            "completion_tokens_per_sec": statistics.get("completion_tokens_per_sec", 0),
            "total_tokens": statistics.get("total_tokens", 0),
            "total_time": statistics.get("total_time", 0)
        }
        
        return f"data: {json.dumps(statistics_event)}\n\n".encode('utf-8')