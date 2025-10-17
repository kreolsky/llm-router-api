"""
Stream Processor Module

This module provides the StreamProcessor class for transparently forwarding
streaming responses from AI providers to clients without any processing
or modification.

The StreamProcessor implements complete transparent proxying, ensuring that
all provider responses are passed through exactly as received.
"""

import json
import time
from typing import Dict, Any, AsyncGenerator, Optional

from ...core.logging import logger
from ...core.exceptions import ProviderStreamError, ProviderNetworkError


class StreamProcessor:
    """
    Transparent stream processor that forwards provider responses with optional sanitization.
    
    This processor implements configurable proxying, ensuring that all
    provider responses are passed through with optional sanitization based on configuration.
    
    Key Features:
    - Configurable sanitization: Can sanitize streaming responses based on SANITIZE_MESSAGES flag
    - Complete transparency: Passes through all provider responses unchanged when sanitization is disabled
    - Error handling: Properly formats errors while maintaining transparency
    - Simple and reliable: Minimal code for maximum reliability
    """
    
    def __init__(self, config_manager=None):
        """
        Initialize StreamProcessor with optional config manager for sanitization.
        
        Args:
            config_manager: Configuration manager instance for checking SANITIZE_MESSAGES flag
        """
        self.config_manager = config_manager
        self.should_sanitize = self._determine_sanitization_status()
        
        # Метрики для отслеживания
        self.total_chunks_processed = 0
        self.total_chunks_sanitized = 0
        
        # Импортируем санитайзер только если нужен
        self._message_sanitizer = None
        if self.should_sanitize:
            from ...core.sanitizer import MessageSanitizer
            self._message_sanitizer = MessageSanitizer
            logger.info(f"StreamProcessor initialized with sanitization enabled", extra={
                "stream_processor": {
                    "sanitization_enabled": True,
                    "service_fields": self._message_sanitizer.SERVICE_FIELDS
                }
            })
        else:
            logger.info("StreamProcessor initialized in transparent mode", extra={
                "stream_processor": {
                    "sanitization_enabled": False
                }
            })
    
    def _determine_sanitization_status(self) -> bool:
        """
        Определяет статус санитизации на основе конфигурации
        
        Returns:
            True если санитизация включена, иначе False
        """
        if not self.config_manager:
            logger.debug("No config manager provided, sanitization disabled")
            return False
        
        try:
            should_sanitize = self.config_manager.should_sanitize_messages
            logger.debug(f"Sanitization status: {should_sanitize}")
            return should_sanitize
        except Exception as e:
            logger.warning(f"Error determining sanitization status: {e}, defaulting to disabled")
            return False
    
    async def process_stream(self,
                           provider_stream: AsyncGenerator[bytes, None],
                           model_id: str,
                           request_id: str,
                           user_id: str) -> AsyncGenerator[bytes, None]:
        """
        Process stream with optional sanitization and comprehensive logging.
        
        Args:
            provider_stream: Raw byte stream from the provider
            model_id: ID of the model being used for the request
            request_id: Unique identifier for the request for logging and tracking
            user_id: Identifier for the user making the request
            
        Yields:
            bytes: Chunks from the provider, optionally sanitized
        """
        start_time = time.time()
        chunk_count = 0
        sanitized_count = 0
        bytes_processed = 0
        
        # Логирование режима работы
        if self.should_sanitize:
            logger.info("Starting stream processing with sanitization enabled", extra={
                "request_id": request_id,
                "user_id": user_id,
                "model": model_id,
                "stream_processing": {
                    "sanitization_enabled": True,
                    "start_time": start_time
                }
            })
        else:
            logger.info("Starting transparent stream processing", extra={
                "request_id": request_id,
                "user_id": user_id,
                "model": model_id,
                "stream_processing": {
                    "sanitization_enabled": False
                }
            })
        
        try:
            async for chunk in provider_stream:
                chunk_count += 1
                bytes_processed += len(chunk)
                
                if self.should_sanitize:
                    original_chunk = chunk
                    sanitized_chunk = self._sanitize_chunk_if_needed(chunk, request_id)
                    
                    # Проверяем, был ли чанк изменен
                    if sanitized_chunk != original_chunk:
                        sanitized_count += 1
                        logger.debug(f"Chunk {chunk_count} was sanitized", extra={
                            "request_id": request_id,
                            "stream_processing": {
                                "chunk_number": chunk_count,
                                "original_size": len(original_chunk),
                                "sanitized_size": len(sanitized_chunk),
                                "was_sanitized": True
                            }
                        })
                    
                    yield sanitized_chunk
                else:
                    logger.debug(f"Passing through chunk {chunk_count} without sanitization", extra={
                        "request_id": request_id,
                        "stream_processing": {
                            "chunk_number": chunk_count,
                            "chunk_size": len(chunk),
                            "was_sanitized": False
                        }
                    })
                    yield chunk
            
            # Финальная статистика
            end_time = time.time()
            duration = end_time - start_time
            
            logger.info(f"Stream processing completed successfully", extra={
                "request_id": request_id,
                "user_id": user_id,
                "model": model_id,
                "stream_processing": {
                    "duration_seconds": duration,
                    "total_chunks": chunk_count,
                    "sanitized_chunks": sanitized_count,
                    "bytes_processed": bytes_processed,
                    "sanitization_ratio": sanitized_count / chunk_count if chunk_count > 0 else 0,
                    "chunks_per_second": chunk_count / duration if duration > 0 else 0,
                    "bytes_per_second": bytes_processed / duration if duration > 0 else 0
                }
            })
            
            # Обновляем глобальные метрики
            self.total_chunks_processed += chunk_count
            self.total_chunks_sanitized += sanitized_count
            
        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time
            
            logger.error(f"Stream processing failed", extra={
                "request_id": request_id,
                "user_id": user_id,
                "model": model_id,
                "stream_processing": {
                    "duration_seconds": duration,
                    "chunks_processed": chunk_count,
                    "sanitized_chunks": sanitized_count,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            }, exc_info=True)
            
            yield self._format_error(e)
    
    def _sanitize_chunk_if_needed(self, chunk: bytes, request_id: str) -> bytes:
        """
        Применяет санитизацию к чанку если это SSE с JSON данными
        
        Args:
            chunk: Байты чанка от провайдера
            request_id: ID запроса для логирования
            
        Returns:
            bytes: Санитизированный чанк или оригинальный если санитизация не нужна
        """
        try:
            chunk_str = chunk.decode('utf-8')
            
            # Пропускаем служебные SSE сообщения
            if not chunk_str.startswith('data: ') or chunk_str.strip() == 'data: [DONE]':
                logger.debug(f"Skipping SSE control message: {chunk_str.strip()}", extra={
                    "request_id": request_id,
                    "sanitization": {
                        "skipped_reason": "sse_control_message",
                        "message": chunk_str.strip()
                    }
                })
                return chunk
            
            # Извлекаем JSON данные
            json_str = chunk_str[6:]  # Убираем 'data: '
            if json_str.strip() == '[DONE]':
                logger.debug("Skipping [DONE] message", extra={
                    "request_id": request_id,
                    "sanitization": {
                        "skipped_reason": "done_message"
                    }
                })
                return chunk
            
            # Парсим JSON
            chunk_data = json.loads(json_str)
            
            # Логируем перед санитизацией
            logger.debug(f"Processing chunk for sanitization", extra={
                "request_id": request_id,
                "sanitization": {
                    "chunk_keys": list(chunk_data.keys()),
                    "has_choices": "choices" in chunk_data,
                    "choices_count": len(chunk_data.get("choices", [])),
                    "chunk_preview": json.dumps(chunk_data)[:200] + "..." if len(json.dumps(chunk_data)) > 200 else json.dumps(chunk_data)
                }
            })
            
            # Применяем санитизацию
            sanitized_data = self._message_sanitizer.sanitize_stream_chunk(
                chunk_data,
                enabled=True
            )
            
            # Возвращаем в том же формате
            return f"data: {json.dumps(sanitized_data)}\n\n".encode('utf-8')
            
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"Could not parse chunk for sanitization", extra={
                "request_id": request_id,
                "sanitization": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "chunk_preview": chunk[:100].decode('utf-8', errors='ignore') + "..." if len(chunk) > 100 else chunk.decode('utf-8', errors='ignore')
                }
            })
            return chunk
    
    def get_processing_stats(self) -> Dict[str, Any]:
        """
        Возвращает статистику обработки стримов
        """
        return {
            "total_chunks_processed": self.total_chunks_processed,
            "total_chunks_sanitized": self.total_chunks_sanitized,
            "sanitization_ratio": self.total_chunks_sanitized / self.total_chunks_processed if self.total_chunks_processed > 0 else 0,
            "sanitization_enabled": self.should_sanitize
        }
    
    def _format_error(self, error: Exception) -> bytes:
        """
        Formats an error in SSE format for transparent error forwarding.
        
        Args:
            error: Exception to format
            
        Returns:
            bytes: Formatted error chunk in SSE format
        """
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