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
from ...core.error_handling import ErrorHandler, ErrorContext
from fastapi import HTTPException


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
            logger.debug(f"Sanitization status: {should_sanitize}", extra={
                "sanitization_status": should_sanitize
            })
            return should_sanitize
        except Exception as e:
            logger.warning(f"Error determining sanitization status: {e}, defaulting to disabled", extra={
                "error_message": str(e),
                "error_type": "sanitization_status_error"
            })
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
        
        logger.info("Starting stream processing", extra={
            "request_id": request_id,
            "user_id": user_id,
            "model": model_id,
            "sanitization_enabled": self.should_sanitize
        })
        
        try:
            # Buffer for partial SSE messages
            buffer = ""
            byte_buffer = b""
            
            # Check if we should use buffering at all
            # If sanitization is disabled, we don't need to buffer
            if not self.should_sanitize:
                is_debug = logger.is_debug_enabled()
                async for chunk in provider_stream:
                    chunk_count += 1
                    bytes_processed += len(chunk)

                    if is_debug:
                        preview = chunk.decode('utf-8', errors='replace')[:200].replace('\n', '\\n')
                        logger.debug(f"Chunk {chunk_count} ({len(chunk)}B): {preview}", request_id=request_id)

                    yield chunk

                duration = time.time() - start_time
                logger.info("Stream completed (transparent)", extra={
                    "request_id": request_id,
                    "duration": round(duration, 3),
                    "total_bytes": bytes_processed
                })
                return

            async for chunk in provider_stream:
                chunk_count += 1
                bytes_processed += len(chunk)

                byte_buffer += chunk
                try:
                    # Try to decode the entire byte buffer
                    decoded_str = byte_buffer.decode('utf-8')
                    buffer += decoded_str
                    byte_buffer = b"" # Clear if successful
                except UnicodeDecodeError as e:
                    # If it fails, it might be a split character at the end
                    # We'll wait for the next chunk, but only if it's at the very end
                    if e.start > len(byte_buffer) - 4: # UTF-8 max 4 bytes
                         logger.debug(f"Unicode split at end of chunk, buffering {len(byte_buffer)} bytes", extra={"request_id": request_id})
                         continue
                    
                    # If it's not at the end, it's a real error
                    logger.warning(f"Unicode decode error in middle of chunk: {e}", extra={"request_id": request_id})
                    buffer += byte_buffer.decode('utf-8', errors='replace')
                    byte_buffer = b""
                    continue

                # SSE messages are separated by double newlines
                # SSE messages can be separated by \n\n or \r\n\r\n
                # We normalize to \n for easier processing
                normalized_buffer = buffer.replace("\r\n", "\n")
                
                # Log buffer state if it's getting large
                if len(buffer) > 10000:
                    logger.warning(f"Large stream buffer: {len(buffer)} chars", extra={"request_id": request_id})

                # SSE standard says messages are separated by \n\n
                # But some providers might use just \n for comments or other data
                # We look for \n\n to be sure we have a full message
                while "\n\n" in normalized_buffer:
                    # Check for comments (lines starting with :)
                    if normalized_buffer.lstrip().startswith(":"):
                        # Find the end of the comment line
                        if "\n" in normalized_buffer:
                            comment_line, buffer = buffer.split("\n", 1)
                            normalized_buffer = buffer.replace("\r\n", "\n")
                            logger.debug(f"Passing through SSE comment", extra={"request_id": request_id})
                            yield (comment_line + "\n").encode('utf-8')
                            continue
                        else:
                            # Comment is not finished yet
                            break

                    # Find the original separator in the raw buffer to split correctly
                    if "\r\n\r\n" in buffer:
                        message, buffer = buffer.split("\r\n\r\n", 1)
                        sep = "\r\n\r\n"
                    else:
                        message, buffer = buffer.split("\n\n", 1)
                        sep = "\n\n"
                    
                    # Update normalized buffer for the next iteration
                    normalized_buffer = buffer.replace("\r\n", "\n")
                    
                    if not message.strip():
                        yield sep.encode('utf-8')
                        continue

                    sanitized_message = self._sanitize_sse_message(message, request_id)

                    if sanitized_message != message:
                        sanitized_count += 1

                    yield (sanitized_message + sep).encode('utf-8')
            
            # Yield remaining buffer if any
            if buffer.strip():
                sanitized_message = self._sanitize_sse_message(buffer, request_id)
                # Use \n\n as default separator for the last piece
                yield (sanitized_message + "\n\n").encode('utf-8')

            duration = time.time() - start_time
            logger.info("Stream completed (sanitized)", extra={
                "request_id": request_id,
                "duration": round(duration, 3),
                "total_bytes": bytes_processed,
                "sanitized_messages": sanitized_count
            })

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
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            }, exc_info=True)
            
            yield self._format_error(e)
    
    def _sanitize_sse_message(self, message: str, request_id: str) -> str:
        """
        Sanitizes a single SSE message string.
        """
        if not message.startswith('data: '):
            return message
            
        json_str = message[6:].strip()
        if json_str == '[DONE]':
            return message
            
        try:
            chunk_data = json.loads(json_str)
            logger.debug(f"JSON parsed successfully", extra={
                "request_id": request_id,
                "keys": list(chunk_data.keys())
            })
            sanitized_data = self._message_sanitizer.sanitize_stream_chunk(
                chunk_data,
                enabled=True
            )
            result = f"data: {json.dumps(sanitized_data, ensure_ascii=False)}"
            logger.debug(f"Sanitization complete (len={len(result)})", extra={"request_id": request_id})
            return result
        except json.JSONDecodeError as e:
            if not json_str.startswith('{') and not json_str.startswith('['):
                logger.debug("Non-JSON SSE message, passing through", extra={
                    "request_id": request_id,
                    "content": json_str[:50]
                })
            else:
                logger.warning("Could not parse SSE message for sanitization", extra={
                    "request_id": request_id,
                    "error": str(e),
                    "message_preview": message[:100]
                })
            return message
    
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
        if isinstance(error, HTTPException):
            # Extract error details from HTTPException
            error_detail = error.detail
            if isinstance(error_detail, dict) and "error" in error_detail:
                # Use the error details from HTTPException
                error_payload = error_detail
            else:
                # Fallback if error_detail is not in expected format
                error_payload = {
                    "error": {
                        "message": str(error_detail) if error_detail else str(error),
                        "type": "api_error",
                        "code": "http_exception",
                        "param": None
                    }
                }
        else:
            # Handle non-HTTPException errors
            message = f"An unexpected error occurred during streaming: {error}"
            error_payload = {
                "error": {
                    "message": message,
                    "type": "api_error",
                    "code": "unexpected_streaming_error",
                    "param": None
                }
            }
        
        return f"data: {json.dumps(error_payload)}\n\n".encode('utf-8')
