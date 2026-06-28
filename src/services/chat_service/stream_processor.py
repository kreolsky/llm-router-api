"""Stream processor for forwarding and optionally sanitizing provider SSE streams."""

import json
import time
from typing import Dict, Any, AsyncGenerator, Optional

from ...core.logging import logger
from ...core.error_handling import ErrorType, create_error
from fastapi import HTTPException


class StreamProcessor:
    """Forwards provider SSE streams with optional message sanitization.

    Holds no per-stream mutable state: every stream runs with its own local
    captured-usage holder so concurrent streams never overwrite each other.
    The sanitization flag is read live from config_manager per stream.
    """

    def __init__(self, config_manager=None):
        self.config_manager = config_manager
        # Resolved lazily on first sanitized stream; import kept lazy to avoid
        # loading the sanitizer module when sanitization is disabled.
        self._message_sanitizer = None
        logger.info("StreamProcessor initialized", extra={
            "stream_processor": {"config_manager": config_manager is not None}
        })

    def _resolve_sanitizer(self):
        if self._message_sanitizer is None:
            from ...core.sanitizer import MessageSanitizer
            self._message_sanitizer = MessageSanitizer
        return self._message_sanitizer

    def _live_sanitization_flag(self) -> bool:
        """Read the sanitization flag live from config_manager."""
        if not self.config_manager:
            return False
        try:
            return self.config_manager.should_sanitize_messages
        except Exception as e:
            logger.warning(f"Error reading sanitization status: {e}, defaulting to disabled", extra={
                "error_message": str(e),
                "error_type": "sanitization_status_error"
            })
            return False

    async def process_stream(self,
                           provider_stream: AsyncGenerator[bytes, None],
                           model_id: str,
                           request_id: str,
                           user_id: str,
                           provider_name: str = "") -> AsyncGenerator[bytes, None]:
        """Process provider stream with optional sanitization.

        Two code paths: when sanitization is disabled, chunks pass through unchanged
        (transparent mode). When enabled, chunks are buffered and decoded as UTF-8,
        split on SSE double-newline boundaries (\\n\\n or \\r\\n\\r\\n), and each
        SSE data message is parsed and sanitized.

        UTF-8 split handling: if a multi-byte character is split at a chunk boundary,
        the partial bytes are buffered until the next chunk completes them.
        """
        should_sanitize = self._live_sanitization_flag()
        # Per-stream mutable holder; never written to self (concurrency-safe).
        captured_usage: Dict[str, Any] = {}

        start_time = time.time()
        chunk_count = 0
        sanitized_count = 0
        bytes_processed = 0

        logger.info("Starting stream processing", extra={
            "request_id": request_id,
            "user_id": user_id,
            "model": model_id,
            "sanitization_enabled": should_sanitize
        })

        try:
            buffer = ""
            byte_buffer = b""

            if not should_sanitize:
                is_debug = logger.is_debug_enabled()
                async for chunk in provider_stream:
                    chunk_count += 1
                    bytes_processed += len(chunk)

                    if is_debug:
                        preview = chunk.decode('utf-8', errors='replace')[:200].replace('\n', '\\n')
                        logger.debug(f"Chunk {chunk_count} ({len(chunk)}B): {preview}", request_id=request_id)

                    yield chunk

                    if b'"usage"' in chunk and b'"prompt_tokens"' in chunk:
                        _capture_usage_from_chunk(chunk, captured_usage)

                duration = time.time() - start_time
                logger.info("Stream completed (transparent)", extra={
                    "request_id": request_id,
                    "duration": round(duration, 3),
                    "total_bytes": bytes_processed
                })
                if captured_usage.get("usage"):
                    _schedule_stream_usage(
                        captured_usage["usage"], request_id, user_id, model_id,
                        start_time, provider_name
                    )
                return

            sanitizer = self._resolve_sanitizer()

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
                    # WHY: UTF-8 chars can be up to 4 bytes; a split in the last 4 bytes is recoverable
                    if e.start > len(byte_buffer) - 4:
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
                            comment_line = comment_line.rstrip("\r")
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

                    sanitized_message = _sanitize_sse_message(
                        message, request_id, sanitizer, captured_usage
                    )

                    if sanitized_message != message:
                        sanitized_count += 1

                    yield (sanitized_message + sep).encode('utf-8')

            # Yield remaining buffer if any
            if buffer.strip():
                sanitized_message = _sanitize_sse_message(
                    buffer, request_id, sanitizer, captured_usage
                )
                # Use \n\n as default separator for the last piece
                yield (sanitized_message + "\n\n").encode('utf-8')

            duration = time.time() - start_time
            logger.info("Stream completed (sanitized)", extra={
                "request_id": request_id,
                "duration": round(duration, 3),
                "total_bytes": bytes_processed,
                "sanitized_messages": sanitized_count
            })
            if captured_usage.get("usage"):
                _schedule_stream_usage(
                    captured_usage["usage"], request_id, user_id, model_id,
                    start_time, provider_name
                )

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

    def _format_error(self, error: Exception) -> bytes:
        """Format an error as an SSE data chunk (OpenRouter-compatible)."""
        if isinstance(error, HTTPException):
            error_detail = error.detail
            if isinstance(error_detail, dict) and "error" in error_detail:
                error_payload = error_detail
            else:
                error_payload = {
                    "error": {
                        "code": error.status_code,
                        "message": str(error_detail) if error_detail else str(error)
                    }
                }
        else:
            error_payload = {
                "error": {
                    "code": 500,
                    "message": f"An unexpected error occurred during streaming: {error}"
                }
            }

        # WHY: many OpenAI-compatible clients block until they see [DONE]; an
        # error frame alone leaves them waiting until the read timeout fires
        return f"data: {json.dumps(error_payload)}\n\ndata: [DONE]\n\n".encode('utf-8')


def _capture_usage_from_chunk(chunk: bytes, captured_usage: Dict[str, Any]) -> None:
    """Parse usage out of a transparent-mode chunk, writing into the holder."""
    try:
        text = chunk.decode('utf-8')
        for line in text.split('\n'):
            if line.startswith('data: ') and line != 'data: [DONE]':
                data = json.loads(line[6:])
                if 'usage' in data:
                    captured_usage["usage"] = data['usage']
    except Exception:
        pass


def _sanitize_sse_message(
    message: str,
    request_id: str,
    sanitizer,
    captured_usage: Dict[str, Any],
) -> str:
    """Sanitize a single SSE message, stripping service fields from JSON data.

    Only processes lines starting with 'data: ' (SSE data frames).
    Passes '[DONE]' sentinel and non-JSON data lines through unchanged.
    Writes captured usage into the supplied holder (never to module/instance state).
    """
    if not message.startswith('data: '):
        return message

    json_str = message[6:].strip()
    if json_str == '[DONE]':
        return message

    try:
        chunk_data = json.loads(json_str)
        if 'usage' in chunk_data:
            captured_usage["usage"] = chunk_data['usage']
        logger.debug(f"JSON parsed successfully", extra={
            "request_id": request_id,
            "keys": list(chunk_data.keys())
        })
        sanitized_data = sanitizer.sanitize_stream_chunk(chunk_data, enabled=True)
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


def _schedule_stream_usage(usage, request_id, user_id, model_id, start_time, provider_name) -> None:
    """Schedule fire-and-forget usage recording for a completed stream."""
    from ...core.usage_db import schedule_chat_usage
    schedule_chat_usage(
        usage,
        project_name=user_id,
        model_id=model_id,
        request_id=request_id,
        provider_name=provider_name,
        start_time=start_time,
    )
