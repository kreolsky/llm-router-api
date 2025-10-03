"""
Координация обработки стриминга
"""
import json
from typing import AsyncGenerator

from fastapi import status

from .buffer_manager import StreamBufferManager
from .format_processor import StreamFormatProcessor
from .error_handler import StreamingErrorHandler
from .logger import ChatLogger
from ...logging.config import logger


class StreamingHandler:
    """Координация обработки стриминга"""
    
    def __init__(self, buffer_manager: StreamBufferManager, 
                 format_processor: StreamFormatProcessor,
                 error_handler: StreamingErrorHandler,
                 chat_logger: ChatLogger):
        self.buffer_manager = buffer_manager
        self.format_processor = format_processor
        self.error_handler = error_handler
        self.logger = chat_logger
    
    async def handle_stream(self, response_data, provider_type: str, model_id: str,
                          request_id: str, user_id: str) -> AsyncGenerator[bytes, None]:
        """
        Основной метод обработки стриминга
        
        Args:
            response_data: Ответ от провайдера
            provider_type: Тип провайдера
            model_id: ID модели
            request_id: ID запроса
            user_id: ID пользователя
            
        Yields:
            Чанки данных в SSE формате
        """
        full_content = ""
        stream_completed_usage = None
        stream_has_error = False
        stream_format = None
        first_chunk = True
        
        try:
            async for chunk in response_data.body_iterator:
                try:
                    # Обработка чанка
                    decoded_chunk = self.buffer_manager.process_chunk(chunk)
                    
                    if not decoded_chunk:
                        continue
                    
                    # Определение формата при первом чанке
                    if first_chunk:
                        first_chunk = False
                        stream_format = self.format_processor.detect_format(decoded_chunk)
                        logger.info(f"Auto-detected {stream_format} format for request {request_id}",
                                  extra={"request_id": request_id, "provider_type": provider_type})
                    
                    # Обработка в зависимости от формата
                    if stream_format == 'ndjson':
                        self.buffer_manager.add_to_json_buffer(decoded_chunk)
                        lines = self.buffer_manager.get_json_lines()
                        
                        for line in lines:
                            processed_chunk, content, usage = self.format_processor.process_ndjson_line(
                                line, model_id, request_id
                            )
                            if content:
                                full_content += content
                            if usage:
                                stream_completed_usage = usage
                            if processed_chunk:
                                yield processed_chunk
                                
                    elif stream_format == 'sse':
                        self.buffer_manager.add_to_sse_buffer(decoded_chunk)
                        events = self.buffer_manager.get_sse_events()
                        
                        for event in events:
                            full_content, stream_completed_usage = self.format_processor.process_sse_event(
                                event, full_content, stream_completed_usage
                            )
                            # Отправляем событие с правильным SSE форматированием
                            yield f"{event}\n\n".encode('utf-8')
                    
                except Exception as e:
                    error_chunk = self.error_handler.handle_streaming_error(e, request_id, user_id)
                    yield error_chunk
                    stream_has_error = True
                    break
                    
        except Exception as e:
            logger.error(f"Critical error before stream iteration for request {request_id}: {e}", 
                        extra={"request_id": request_id, "user_id": user_id, "log_type": "error"}, 
                        exc_info=True)
            error_chunk = self.error_handler.handle_streaming_error(e, request_id, user_id)
            yield error_chunk
            stream_has_error = True
        
        # Обработка оставшихся данных в буферах
        if not stream_has_error:
            sse_buffer, json_buffer = self.buffer_manager.get_remaining_data()
            
            if stream_format == 'sse' and sse_buffer.strip():
                full_content, stream_completed_usage = self.format_processor.process_sse_event(
                    sse_buffer, full_content, stream_completed_usage
                )
                yield f"{sse_buffer}\n\n".encode('utf-8')
            elif stream_format == 'ndjson' and json_buffer.strip():
                try:
                    processed_chunk, content, usage = self.format_processor.process_ndjson_line(
                        json_buffer, model_id, request_id
                    )
                    if content:
                        full_content += content
                    if usage:
                        stream_completed_usage = usage
                    if processed_chunk:
                        yield processed_chunk
                except:
                    pass  # Игнорируем ошибки в финальной обработке буфера
            
            # Логирование завершения
            self.logger.log_streaming_completion(request_id, user_id, model_id, full_content, stream_completed_usage)
            yield b"data: [DONE]\n\n"
        else:
            logger.warning(f"Stream terminated with error for request {request_id}, skipping [DONE]",
                         extra={"request_id": request_id, "user_id": user_id, "log_type": "warning"})
        
        # Очистка буферов
        self.buffer_manager.clear_buffers()