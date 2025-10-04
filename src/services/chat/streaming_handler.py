"""
Координация обработки стриминга
"""
from typing import AsyncGenerator, Dict, Any, Optional

from fastapi import status

from .parsed_event import ParsedStreamEvent
from .smart_buffer_manager import SmartStreamBufferManager
from .format_processor import StreamFormatProcessor
from .error_handler import StreamingErrorHandler
from ...logging.config import logger


class StreamingHandler:
    """
    Координация обработки стриминга с единой логикой
    """
    
    def __init__(self, buffer_manager: SmartStreamBufferManager,
                 format_processor: StreamFormatProcessor,
                 error_handler: StreamingErrorHandler):
        self.buffer_manager = buffer_manager
        self.format_processor = format_processor
        self.error_handler = error_handler
    
    async def handle_stream(self, response_data, provider_type: str, model_id: str,
                          request_id: str, user_id: str,
                          stream_format: Optional[str] = None) -> AsyncGenerator[bytes, None]:
        """
        Основной метод обработки стриминга
        
        Args:
            response_data: Ответ от провайдера
            provider_type: Тип провайдера
            model_id: ID модели
            request_id: ID запроса
            user_id: ID пользователя
            stream_format: Предопределенный формат (опционально)
        """
        full_content = ""
        stream_completed_usage = None
        stream_has_error = False
        
        # Логирование начала (единожды)
        logger.info(f"Starting stream processing", extra={
            "request_id": request_id,
            "user_id": user_id,
            "model": model_id,
            "provider": provider_type,
            "format": stream_format or "auto-detect"
        })
        
        try:
            async for chunk in response_data.body_iterator:
                try:
                    # Получаем ParsedStreamEvent с кешированным JSON
                    parsed_events = self.buffer_manager.process_chunk(chunk)
                    
                    # Обрабатываем каждое событие
                    for event in parsed_events:
                        # Унифицированная обработка
                        result = await self._process_event(
                            event, model_id, request_id, full_content, stream_completed_usage
                        )
                        
                        if result.chunk:
                            yield result.chunk
                        
                        full_content = result.content
                        stream_completed_usage = result.usage
                        
                except Exception as e:
                    # Единственное место логирования ошибок!
                    logger.error(f"Stream processing error", extra={
                        "request_id": request_id,
                        "user_id": user_id,
                        "error": str(e),
                        "error_type": type(e).__name__
                    }, exc_info=True)
                    
                    error_chunk = self.error_handler.format_streaming_error(e)
                    yield error_chunk
                    stream_has_error = True
                    break
                    
        except Exception as e:
            logger.error(f"Critical stream error", extra={
                "request_id": request_id,
                "user_id": user_id,
                "error": str(e)
            }, exc_info=True)
            
            error_chunk = self.error_handler.format_streaming_error(e)
            yield error_chunk
            stream_has_error = True
        
        # Обработка оставшихся данных
        if not stream_has_error:
            remaining = self.buffer_manager.get_remaining_data()
            
            if remaining.is_valid and remaining.raw.strip():
                result = await self._process_event(
                    remaining, model_id, request_id, full_content, stream_completed_usage
                )
                
                if result.chunk:
                    yield result.chunk
                
                full_content = result.content
                stream_completed_usage = result.usage
            
            # Логирование завершения (единожды)
            logger.info("Stream completed", extra={
                "request_id": request_id,
                "user_id": user_id,
                "model": model_id,
                "content_length": len(full_content),
                "usage": stream_completed_usage
            })
            
            yield b"data: [DONE]\n\n"
        
        # Очистка
        self.buffer_manager.clear_buffers()
    
    async def _process_event(self, event: ParsedStreamEvent, model_id: str,
                            request_id: str, full_content: str,
                            usage: Optional[Dict[str, Any]]) -> 'ProcessingResult':
        """
        Унифицированная обработка события любого формата
        
        Args:
            event: ParsedStreamEvent
            model_id: ID модели
            request_id: ID запроса
            full_content: Текущий контент
            usage: Текущие данные об использовании
            
        Returns:
            ProcessingResult с результатами
        """
        if not event.is_valid or not event.data:
            return ProcessingResult(chunk=None, content=full_content, usage=usage)
        
        # Обработка через format_processor (БЕЗ повторного парсинга!)
        new_content, new_usage = self.format_processor.process_parsed_event(
            event, full_content, usage or {}
        )
        
        # Формирование чанка в зависимости от формата
        if event.format == 'ndjson':
            chunk = self.format_processor.format_ndjson_to_sse(event, model_id, request_id)
        else:
            # SSE передаем как есть
            chunk = f"{event.raw}\n\n".encode('utf-8')
        
        return ProcessingResult(
            chunk=chunk if chunk else None,
            content=new_content,
            usage=new_usage if new_usage else usage
        )


class ProcessingResult:
    """Результат обработки события"""
    def __init__(self, chunk: Optional[bytes], content: str, usage: Optional[Dict[str, Any]]):
        self.chunk = chunk
        self.content = content
        self.usage = usage