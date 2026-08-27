"""Stream processor for forwarding and optionally sanitizing provider SSE streams."""
# SYSTEM: sse-stream — SSE frame parsing, passthrough and sanitizing bodies

import json
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Dict, Optional, Tuple

from ...core.logging import logger
from ...core.usage_db import RequestStats
from ...core.error_handling import ErrorType, create_error
from ...core.sanitizer import MessageSanitizer
from fastapi import HTTPException


def duplicate_reasoning_field(data: Any) -> bool:
    """Duplicate OpenAI-style 'reasoning' into llama.cpp-style 'reasoning_content'.

    vLLM (and some other backends) stream thinking into delta/message.reasoning,
    while clients in this lab were built against llama.cpp, which emits
    reasoning_content. Duplicating keeps both client styles working; the
    original field is left intact. Returns True when the data was modified.
    """
    if not isinstance(data, dict):
        return False
    choices = data.get("choices")
    if not isinstance(choices, list):
        return False
    changed = False
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        for holder in (choice.get("message"), choice.get("delta")):
            if (isinstance(holder, dict) and "reasoning" in holder
                    and "reasoning_content" not in holder):
                holder["reasoning_content"] = holder["reasoning"]
                changed = True
    return changed


async def open_provider_stream(
        provider_stream: AsyncGenerator[bytes, None]) -> AsyncGenerator[bytes, None]:
    """Pull the first chunk eagerly, then return an equivalent stream.

    # WHY: a provider generator does nothing until it is iterated, and iteration
    # starts inside StreamingResponse — after the 200 and the response headers
    # have already gone out. An upstream 401/429 then reached the client as a
    # 200 carrying an SSE error frame, losing the status code entirely.
    #
    # Priming moves the first read (which is where upstream errors surface) in
    # front of the response, so the HTTPException propagates through the normal
    # error handler and the client gets the real status. If the first read
    # raises, the generator is already finished, so its cleanup — the in-flight
    # count and the concurrency slot — has run.
    """
    try:
        first_chunk = await provider_stream.__anext__()
    except StopAsyncIteration:
        return _empty_stream()
    return _prepend(first_chunk, provider_stream)


async def _empty_stream() -> AsyncGenerator[bytes, None]:
    """An already-exhausted byte stream."""
    return
    yield  # pragma: no cover - makes this an async generator


async def _prepend(first_chunk: bytes,
                   rest: AsyncGenerator[bytes, None]) -> AsyncGenerator[bytes, None]:
    """Re-attach an already-consumed first chunk to the front of a stream.

    # INVARIANT: closing this wrapper must close the wrapped stream. Without the
    # finally, a client disconnect throws GeneratorExit in here and leaves `rest`
    # suspended, so the provider's in-flight count and concurrency slot are never
    # released — and a config reload would then wait out the full drain timeout.
    """
    try:
        yield first_chunk
        async for chunk in rest:
            yield chunk
    finally:
        await rest.aclose()


class StreamProcessor:
    """Forwards provider SSE streams with optional message sanitization.

    Holds no per-stream mutable state: every stream runs with its own local
    captured-usage holder so concurrent streams never overwrite each other.
    The sanitization flag is read live from config_manager per stream.
    """

    def __init__(self, config_manager=None):
        self.config_manager = config_manager
        logger.info("StreamProcessor initialized", extra={
            "stream_processor": {"config_manager": config_manager is not None}
        })

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
                           provider_name: str = "",
                           stats: Optional[RequestStats] = None) -> AsyncGenerator[bytes, None]:
        """Forward a provider SSE stream, optionally sanitizing it on the way.

        Two independent bodies share only this envelope (logging, usage capture,
        error framing):

        - transparent (_passthrough): chunks are forwarded byte-for-byte;
        - sanitizing (_sanitizing): the byte stream is decoded, split into SSE
          frames and each data frame is parsed and stripped of service fields.

        The sanitization flag is read once per stream, and captured usage lives
        in a per-stream holder, so concurrent streams never affect each other.

        The per-request RequestStats holder is enriched in place: mid-stream
        failures write error_code/error_message from the same payload as the
        SSE error frame (so the frame and the row cannot drift), and set_usage
        runs in a ``finally`` so the error path and a client disconnect keep
        partial usage.
        """
        should_sanitize = self._live_sanitization_flag()
        captured_usage: Dict[str, Any] = {}
        # Throwaway holder when the caller passed none (unit tests): the
        # enrichment below stays identical, it just goes nowhere.
        req_stats = stats if stats is not None else RequestStats()
        chunk_stats = _StreamStats()
        start_time = time.time()

        logger.info("Starting stream processing", extra={
            "request_id": request_id,
            "user_id": user_id,
            "model": model_id,
            "sanitization_enabled": should_sanitize
        })

        body = (self._sanitizing(provider_stream, request_id, captured_usage, chunk_stats)
                if should_sanitize
                else self._passthrough(provider_stream, request_id, captured_usage, chunk_stats))

        try:
            async for chunk in body:
                yield chunk
        except Exception as e:
            logger.error("Stream processing failed", extra={
                "request_id": request_id,
                "user_id": user_id,
                "model": model_id,
                "stream_processing": {
                    "duration_seconds": time.time() - start_time,
                    "chunks_processed": chunk_stats.chunks,
                    "error": str(e),
                    "error_type": type(e).__name__
                }
            }, exc_info=True)
            error_payload = _error_payload(e)
            _apply_stream_error(req_stats, error_payload)
            yield _frame_error(error_payload)
            return
        finally:
            if captured_usage.get("usage"):
                req_stats.set_usage(captured_usage["usage"])

        logger.info(
            "Stream completed (sanitized)" if should_sanitize else "Stream completed (transparent)",
            extra={
                "request_id": request_id,
                "duration": round(time.time() - start_time, 3),
                "total_bytes": chunk_stats.bytes,
                "sanitized_messages": chunk_stats.sanitized,
            })

    async def _passthrough(self,
                           provider_stream: AsyncGenerator[bytes, None],
                           request_id: str,
                           captured_usage: Dict[str, Any],
                           stats: "_StreamStats") -> AsyncGenerator[bytes, None]:
        """Forward chunks unchanged, only peeking for reasoning fields and usage.

        Both peeks are gated on a raw byte substring test, so a chunk that
        carries neither costs one scan and no parsing.
        """
        is_debug = logger.is_debug_enabled()
        async for chunk in provider_stream:
            stats.chunks += 1
            stats.bytes += len(chunk)

            if is_debug:
                preview = chunk.decode('utf-8', errors='replace')[:200].replace('\n', '\\n')
                logger.debug(f"Chunk {stats.chunks} ({len(chunk)}B): {preview}", request_id=request_id)

            if b'"reasoning"' in chunk:
                chunk = _remap_reasoning_in_chunk(chunk)

            yield chunk

            if b'"usage"' in chunk and b'"prompt_tokens"' in chunk:
                _capture_usage_from_chunk(chunk, captured_usage)

    async def _sanitizing(self,
                          provider_stream: AsyncGenerator[bytes, None],
                          request_id: str,
                          captured_usage: Dict[str, Any],
                          stats: "_StreamStats") -> AsyncGenerator[bytes, None]:
        """Decode, re-frame and sanitize each SSE message before forwarding it."""
        sanitizer = MessageSanitizer
        text_stream = _decode_chunks(provider_stream, request_id, stats)

        async for message, separator in _iter_sse_frames(text_stream, request_id):
            sanitized = _sanitize_sse_message(message, request_id, sanitizer, captured_usage)
            if sanitized != message:
                stats.sanitized += 1
            yield (sanitized + separator).encode('utf-8')

    def _format_error(self, error: Exception) -> bytes:
        """Format an error as an SSE data chunk (OpenRouter-compatible)."""
        return _frame_error(_error_payload(error))


# Separator styles an SSE producer may use, and the one we fall back to when a
# stream ends without a trailing blank line.
_SEPARATORS = ("\r\n\r\n", "\n\n")
_DEFAULT_SEPARATOR = "\n\n"
# A frame this large means the producer is not framing at all; worth a warning.
_LARGE_BUFFER_WARN = 10000
# Longest UTF-8 sequence, i.e. how far back a split character can start.
_MAX_UTF8_CHAR_BYTES = 4


@dataclass
class _StreamStats:
    """Per-stream counters used only for the completion and failure log lines."""
    chunks: int = 0
    bytes: int = 0
    sanitized: int = 0


async def _decode_chunks(provider_stream: AsyncGenerator[bytes, None],
                         request_id: str,
                         stats: _StreamStats) -> AsyncGenerator[str, None]:
    """Decode a byte stream to text, healing multi-byte characters split across chunks.

    A UTF-8 character can span up to 4 bytes and a chunk boundary can land in the
    middle of one. When the decode error starts within the last 4 bytes the tail
    is held back and completed by the next chunk; an error anywhere earlier is a
    genuinely malformed stream and is decoded with replacement characters.
    """
    pending = b""
    async for chunk in provider_stream:
        stats.chunks += 1
        stats.bytes += len(chunk)
        pending += chunk
        try:
            text = pending.decode('utf-8')
        except UnicodeDecodeError as e:
            if e.start > len(pending) - _MAX_UTF8_CHAR_BYTES:
                logger.debug(
                    f"Unicode split at end of chunk, buffering {len(pending)} bytes",
                    extra={"request_id": request_id})
                continue
            logger.warning(f"Unicode decode error in middle of chunk: {e}",
                           extra={"request_id": request_id})
            text = pending.decode('utf-8', errors='replace')
        pending = b""
        yield text


def _split_frame(buffer: str) -> Optional[Tuple[str, str, str]]:
    """Split one complete SSE frame off the buffer.

    Returns (payload, separator, rest), or None when the buffer holds no
    complete frame yet. The payload is returned verbatim — comments and empty
    frames included — because the caller passes anything that is not a
    ``data:`` line straight through.
    """
    normalized = buffer.replace("\r\n", "\n")
    if "\n\n" not in normalized:
        return None

    # A comment (": keep-alive") is terminated by a single newline, not a blank line.
    if normalized.lstrip().startswith(":"):
        if "\n" not in buffer:
            return None
        comment, rest = buffer.split("\n", 1)
        return comment.rstrip("\r"), "\n", rest

    # WHY: pick the separator that occurs FIRST, not whichever is present. A
    # buffer holding "a\n\nb\r\n\r\n" must yield "a", or the two messages are
    # merged into one malformed frame.
    positions = [(buffer.find(sep), sep) for sep in _SEPARATORS]
    index, separator = min((pos, sep) for pos, sep in positions if pos != -1)
    return buffer[:index], separator, buffer[index + len(separator):]


async def _iter_sse_frames(text_stream: AsyncGenerator[str, None],
                           request_id: str) -> AsyncGenerator[Tuple[str, str], None]:
    """Re-frame a text stream into (payload, separator) SSE messages.

    Any trailing content left when the stream ends is emitted as a final frame
    with the default separator, so a provider that omits the last blank line
    does not lose its closing message.
    """
    buffer = ""
    warned = False
    async for text in text_stream:
        buffer += text
        if len(buffer) > _LARGE_BUFFER_WARN and not warned:
            warned = True
            logger.warning(f"Large stream buffer: {len(buffer)} chars",
                           extra={"request_id": request_id})
        while (frame := _split_frame(buffer)) is not None:
            payload, separator, buffer = frame
            yield payload, separator
    if buffer.strip():
        yield buffer, _DEFAULT_SEPARATOR


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


def _remap_reasoning_in_chunk(chunk: bytes) -> bytes:
    """Best-effort reasoning->reasoning_content duplication for a raw transparent-mode chunk.

    Only rewrites 'data: ' lines that parse as complete JSON objects; a line
    split across chunk boundaries fails to parse here and passes through
    unchanged (it will be handled on its completing chunk or, worst case,
    reach the client with the original field name only).
    """
    try:
        text = chunk.decode('utf-8')
    except UnicodeDecodeError:
        return chunk
    out_lines = []
    changed = False
    for line in text.split('\n'):
        stripped = line.rstrip('\r')
        if stripped.startswith('data: ') and '"reasoning"' in stripped:
            try:
                data = json.loads(stripped[6:])
            except json.JSONDecodeError:
                out_lines.append(line)
                continue
            if duplicate_reasoning_field(data):
                changed = True
                line = 'data: ' + json.dumps(data, ensure_ascii=False)
        out_lines.append(line)
    if not changed:
        return chunk
    return '\n'.join(out_lines).encode('utf-8')


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
        duplicate_reasoning_field(chunk_data)
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


def _error_payload(error: Exception) -> Dict[str, Any]:
    """Build the OpenRouter-shaped error payload for a mid-stream failure.

    Single construction point shared by the SSE error frame and the stats
    enrichment, so the frame the client sees and the row the dashboard sees
    cannot drift.
    """
    if isinstance(error, HTTPException):
        error_detail = error.detail
        if isinstance(error_detail, dict) and "error" in error_detail:
            return error_detail
        return {
            "error": {
                "code": error.status_code,
                "message": str(error_detail) if error_detail else str(error)
            }
        }
    return {
        "error": {
            "code": 500,
            "message": f"An unexpected error occurred during streaming: {error}"
        }
    }


def _frame_error(error_payload: Dict[str, Any]) -> bytes:
    """Frame an error payload as SSE data.

    WHY: many OpenAI-compatible clients block until they see [DONE]; an
    error frame alone leaves them waiting until the read timeout fires.
    """
    return f"data: {json.dumps(error_payload)}\n\ndata: [DONE]\n\n".encode('utf-8')


def _apply_stream_error(stats: RequestStats, error_payload: Dict[str, Any]) -> None:
    """Write error_code / error_message into the stats holder.

    HTTPException → its metadata.error_code (always present for errors raised
    via create_error / create_provider_http_error). Any other exception →
    internal_server_error, coarse by design: error_message carries the detail.
    """
    error = error_payload.get("error") or {}
    metadata = error.get("metadata") or {}
    error_code = metadata.get("error_code") if isinstance(metadata, dict) else None
    stats.error_code = error_code or "internal_server_error"
    message = error.get("message")
    stats.error_message = str(message) if message is not None else None
