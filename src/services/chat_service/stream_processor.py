"""Stream processor for forwarding provider SSE streams."""
# SYSTEM: sse-stream — passthrough streaming body

import json
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from ...core.error_handling import enrich_stats_from_envelope
from ...core.logging import logger
from ...core.usage_db import RequestStats


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
    """Forwards provider SSE streams.

    Holds no per-stream mutable state: every stream runs with its own local
    captured-usage holder so concurrent streams never overwrite each other.
    """

    def __init__(self):
        logger.info("StreamProcessor initialized", extra={
            "stream_processor": {}
        })

    async def process_stream(self,
                           provider_stream: AsyncGenerator[bytes, None],
                           model_id: str,
                           request_id: str,
                           user_id: str,
                           provider_name: str = "",
                           stats: RequestStats | None = None) -> AsyncGenerator[bytes, None]:
        """Forward a provider SSE stream byte-for-byte (logging, usage capture,
        error framing).

        Captured usage lives in a per-stream holder, so concurrent streams
        never affect each other.

        The per-request RequestStats holder is enriched in place: mid-stream
        failures write error_code/error_message from the same payload as the
        SSE error frame (so the frame and the row cannot drift), and set_usage
        runs in a ``finally`` so the error path and a client disconnect keep
        partial usage.
        """
        captured_usage: dict[str, Any] = {}
        # Throwaway holder when the caller passed none (unit tests): the
        # enrichment below stays identical, it just goes nowhere.
        req_stats = stats if stats is not None else RequestStats()
        chunk_stats = _StreamStats()
        start_time = time.time()

        logger.info("Starting stream processing", extra={
            "request_id": request_id,
            "user_id": user_id,
            "model": model_id
        })

        try:
            async for chunk in self._passthrough(provider_stream, request_id, captured_usage, chunk_stats):
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
            # The ONE envelope extractor (core/error_handling/envelope.py),
            # shared with the HTTP exception handler: the frame the client
            # sees and the row the dashboard sees cannot drift.
            enrich_stats_from_envelope(
                req_stats, error_payload, default_error_code="internal_server_error"
            )
            yield _frame_error(error_payload)
            return
        finally:
            if captured_usage.get("usage"):
                req_stats.set_usage(captured_usage["usage"])

        logger.info("Stream completed", extra={
                "request_id": request_id,
                "duration": round(time.time() - start_time, 3),
                "total_bytes": chunk_stats.bytes
            })

    async def _passthrough(self,
                           provider_stream: AsyncGenerator[bytes, None],
                           request_id: str,
                           captured_usage: dict[str, Any],
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


@dataclass
class _StreamStats:
    """Per-stream counters used only for the completion and failure log lines."""
    chunks: int = 0
    bytes: int = 0


def _capture_usage_from_chunk(chunk: bytes, captured_usage: dict[str, Any]) -> None:
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


def _error_payload(error: Exception) -> dict[str, Any]:
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


def _frame_error(error_payload: dict[str, Any]) -> bytes:
    """Frame an error payload as SSE data.

    WHY: many OpenAI-compatible clients block until they see [DONE]; an
    error frame alone leaves them waiting until the read timeout fires.
    """
    return f"data: {json.dumps(error_payload)}\n\ndata: [DONE]\n\n".encode()
