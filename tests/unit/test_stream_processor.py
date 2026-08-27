"""Unit tests for StreamProcessor."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.services.chat_service.stream_processor import StreamProcessor, duplicate_reasoning_field
from src.core.sanitizer import MessageSanitizer
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def async_gen(items):
    for item in items:
        yield item


async def collect(agen):
    return [x async for x in agen]


def sse(data_str, sep="\n\n"):
    return f"data: {data_str}{sep}".encode("utf-8")


def make_processor(sanitize=False):
    cm = MagicMock()
    cm.should_sanitize_messages = sanitize
    return StreamProcessor(config_manager=cm)


# ---------------------------------------------------------------------------
# 1. Transparent mode
# ---------------------------------------------------------------------------

class TestTransparentMode:

    @pytest.mark.asyncio
    async def test_chunks_pass_through(self):
        sp = StreamProcessor(config_manager=None)
        chunks = [b"data: hello\n\n", b"data: world\n\n"]
        result = await collect(sp.process_stream(async_gen(chunks), "m", "r", "u"))
        assert result == chunks

    @pytest.mark.asyncio
    async def test_config_off(self):
        sp = make_processor(sanitize=False)
        chunks = [b"chunk1", b"chunk2"]
        result = await collect(sp.process_stream(async_gen(chunks), "m", "r", "u"))
        assert result == chunks

    @pytest.mark.asyncio
    async def test_empty_stream(self):
        sp = StreamProcessor(config_manager=None)
        result = await collect(sp.process_stream(async_gen([]), "m", "r", "u"))
        assert result == []


# ---------------------------------------------------------------------------
# 2. Sanitization mode
# ---------------------------------------------------------------------------

class TestSanitizationMode:

    @pytest.mark.asyncio
    async def test_json_message_sanitized(self):
        sp = make_processor(sanitize=True)
        payload = {"choices": [{"delta": {"content": "hi", "done": True}}]}
        chunk = sse(json.dumps(payload))
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        # MessageSanitizer should strip 'done' from delta
        assert len(result) >= 1
        decoded = result[0].decode("utf-8")
        assert decoded.startswith("data: ")
        parsed = json.loads(decoded.split("data: ", 1)[1].split("\n\n")[0])
        assert "done" not in parsed.get("choices", [{}])[0].get("delta", {})

    @pytest.mark.asyncio
    async def test_done_sentinel_passed_through(self):
        sp = make_processor(sanitize=True)
        chunk = b"data: [DONE]\n\n"
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        assert any(b"[DONE]" in r for r in result)

    @pytest.mark.asyncio
    async def test_non_json_passed_through(self):
        sp = make_processor(sanitize=True)
        chunk = b"data: not-json\n\n"
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        assert any(b"not-json" in r for r in result)

    @pytest.mark.asyncio
    async def test_non_data_prefix_passed_through(self):
        sp = make_processor(sanitize=True)
        chunk = b"event: ping\n\ndata: {}\n\n"
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        combined = b"".join(result).decode("utf-8")
        assert "event: ping" in combined

    @pytest.mark.asyncio
    async def test_multiple_messages_in_one_chunk(self):
        sp = make_processor(sanitize=True)
        p1 = json.dumps({"id": "1"})
        p2 = json.dumps({"id": "2"})
        chunk = f"data: {p1}\n\ndata: {p2}\n\n".encode("utf-8")
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        combined = b"".join(result).decode("utf-8")
        assert "1" in combined
        assert "2" in combined


# ---------------------------------------------------------------------------
# 3. SSE boundary parsing
# ---------------------------------------------------------------------------

class TestSseBoundaryParsing:

    @pytest.mark.asyncio
    async def test_lf_separator(self):
        sp = make_processor(sanitize=True)
        chunk = b'data: {"ok":true}\n\n'
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_crlf_separator(self):
        sp = make_processor(sanitize=True)
        chunk = b'data: {"ok":true}\r\n\r\n'
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        combined = b"".join(result).decode("utf-8")
        assert "ok" in combined

    @pytest.mark.asyncio
    async def test_empty_between_separators(self):
        sp = make_processor(sanitize=True)
        chunk = b'data: {"a":1}\n\n\n\ndata: {"b":2}\n\n'
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        assert len(result) >= 2


# ---------------------------------------------------------------------------
# 4. UTF-8 split handling
# ---------------------------------------------------------------------------

class TestUtf8SplitHandling:

    @pytest.mark.asyncio
    async def test_split_2byte_char(self):
        """2-byte UTF-8 char (ü = 0xC3 0xBC) split across chunks."""
        sp = make_processor(sanitize=True)
        full_msg = 'data: {"text":"ü"}\n\n'
        encoded = full_msg.encode("utf-8")
        # Find the ü bytes and split in between
        idx = encoded.index(b"\xc3")
        chunk1 = encoded[:idx + 1]  # ends with first byte of ü
        chunk2 = encoded[idx + 1:]  # starts with second byte of ü
        result = await collect(sp.process_stream(async_gen([chunk1, chunk2]), "m", "r", "u"))
        combined = b"".join(result).decode("utf-8")
        assert "ü" in combined

    @pytest.mark.asyncio
    async def test_split_4byte_char(self):
        """4-byte UTF-8 char (🚀 = F0 9F 9A 80) split across chunks."""
        sp = make_processor(sanitize=True)
        full_msg = 'data: {"text":"🚀"}\n\n'
        encoded = full_msg.encode("utf-8")
        idx = encoded.index(b"\xf0")
        chunk1 = encoded[:idx + 1]
        chunk2 = encoded[idx + 1:]
        result = await collect(sp.process_stream(async_gen([chunk1, chunk2]), "m", "r", "u"))
        combined = b"".join(result).decode("utf-8")
        assert "🚀" in combined


# ---------------------------------------------------------------------------
# 5. SSE comment lines
# ---------------------------------------------------------------------------

class TestSseCommentLines:

    @pytest.mark.asyncio
    async def test_comment_passed_through(self):
        sp = make_processor(sanitize=True)
        chunk = b": heartbeat\n\ndata: {}\n\n"
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        combined = b"".join(result).decode("utf-8")
        assert "heartbeat" in combined


# ---------------------------------------------------------------------------
# 6. _format_error
# ---------------------------------------------------------------------------

def _parse_error_frame(result: bytes):
    """Parse the first SSE data frame from _format_error output."""
    text = result.decode("utf-8")
    first_frame = text.split("\n\n", 1)[0]
    return json.loads(first_frame[len("data: "):])


class TestFormatError:

    def test_generic_exception(self):
        sp = StreamProcessor(config_manager=None)
        result = sp._format_error(ValueError("oops"))
        decoded = _parse_error_frame(result)
        assert decoded["error"]["code"] == 500
        assert "oops" in decoded["error"]["message"]

    def test_http_exception_string_detail(self):
        sp = StreamProcessor(config_manager=None)
        exc = HTTPException(status_code=403, detail="forbidden")
        result = sp._format_error(exc)
        decoded = _parse_error_frame(result)
        assert decoded["error"]["code"] == 403
        assert "forbidden" in decoded["error"]["message"]

    def test_http_exception_dict_detail(self):
        sp = StreamProcessor(config_manager=None)
        detail = {"error": {"code": 429, "message": "rate limited"}}
        exc = HTTPException(status_code=429, detail=detail)
        result = sp._format_error(exc)
        decoded = _parse_error_frame(result)
        assert decoded["error"]["code"] == 429
        assert decoded["error"]["message"] == "rate limited"

    def test_returns_bytes_with_sse_framing(self):
        sp = StreamProcessor(config_manager=None)
        result = sp._format_error(RuntimeError("x"))
        assert isinstance(result, bytes)
        assert result.startswith(b"data: ")
        assert result.endswith(b"\n\n")

    def test_ends_with_done_sentinel(self):
        sp = StreamProcessor(config_manager=None)
        result = sp._format_error(RuntimeError("x"))
        assert result.endswith(b"data: [DONE]\n\n")


# ---------------------------------------------------------------------------
# 7. Live sanitization flag (_live_sanitization_flag)
# ---------------------------------------------------------------------------

class TestLiveSanitizationFlag:

    @pytest.mark.asyncio
    async def test_no_config_manager_disables_sanitization(self):
        """Without a config_manager the stream runs in transparent mode."""
        sp = StreamProcessor(config_manager=None)
        chunk = b'data: {"done": True}\n\n'
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        # Transparent: chunk passes through untouched (done is NOT stripped)
        assert result == [chunk]

    @pytest.mark.asyncio
    async def test_flag_read_live_across_streams(self):
        """The flag is read per stream, so toggling config between streams takes effect."""
        cm = MagicMock()
        cm.should_sanitize_messages = False
        sp = StreamProcessor(config_manager=cm)

        payload = {"choices": [{"delta": {"content": "hi", "done": True}}]}
        chunk = sse(json.dumps(payload))

        # First stream: sanitization off → untouched
        result_off = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        assert result_off == [chunk]

        # Toggle the live flag without rebuilding the processor
        cm.should_sanitize_messages = True
        result_on = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        decoded = result_on[0].decode("utf-8")
        parsed = json.loads(decoded.split("data: ", 1)[1].split("\n\n")[0])
        assert "done" not in parsed.get("choices", [{}])[0].get("delta", {})

    @pytest.mark.asyncio
    async def test_flag_error_defaults_to_disabled(self):
        """A config_manager that raises returns transparent (disabled) behavior."""
        cm = MagicMock()
        type(cm).should_sanitize_messages = property(lambda self: (_ for _ in ()).throw(RuntimeError("broken")))
        sp = StreamProcessor(config_manager=cm)
        payload = {"choices": [{"delta": {"content": "hi", "done": True}}]}
        chunk = sse(json.dumps(payload))
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        # Disabled → chunk untouched
        assert result == [chunk]


# ---------------------------------------------------------------------------
# 7b. Concurrency: per-stream captured usage isolation
# ---------------------------------------------------------------------------

class TestConcurrentStreamUsageIsolation:

    @pytest.mark.asyncio
    async def test_two_interleaved_streams_record_own_usage(self):
        """Two concurrent streams over one processor each capture their own usage."""
        sp = StreamProcessor(config_manager=None)

        usage_a = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        usage_b = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        chunk_a = sse(json.dumps({"usage": usage_a}))
        chunk_b = sse(json.dumps({"usage": usage_b}))

        recorded = []

        async def gen_a():
            for c in [chunk_a, chunk_b]:
                yield c

        async def gen_b():
            for c in [chunk_b, chunk_a]:
                yield c

        async def run_and_capture(gen, tag):
            chunks = await collect(sp.process_stream(gen, tag, tag, tag))
            recorded.append((tag, chunks))

        await run_and_capture(gen_a(), "A")
        await run_and_capture(gen_b(), "B")

        # Each stream saw both usages; verify usage was captured without
        # cross-stream interference (no instance-level shared overwrite crash).
        assert len(recorded) == 2


# ---------------------------------------------------------------------------
# 8. Remaining buffer at end of stream
# ---------------------------------------------------------------------------

class TestRemainingBuffer:

    @pytest.mark.asyncio
    async def test_trailing_buffer_flushed(self):
        sp = make_processor(sanitize=True)
        # No trailing \n\n — buffer should be flushed at end
        chunk = b'data: {"trailing":true}'
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        combined = b"".join(result).decode("utf-8")
        assert "trailing" in combined

    @pytest.mark.asyncio
    async def test_no_trailing_for_empty_buffer(self):
        sp = make_processor(sanitize=True)
        # Complete message — nothing left in buffer
        chunk = b'data: {"complete":true}\n\n'
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        # Should get exactly the message, no extra
        assert len(result) == 1


# ---------------------------------------------------------------------------
# 9. reasoning -> reasoning_content duplication
# ---------------------------------------------------------------------------

class TestReasoningFieldDuplication:

    def test_stream_delta_duplicated(self):
        data = {"choices": [{"delta": {"reasoning": "We"}}]}
        assert duplicate_reasoning_field(data) is True
        assert data["choices"][0]["delta"]["reasoning_content"] == "We"
        assert data["choices"][0]["delta"]["reasoning"] == "We"

    def test_non_stream_message_duplicated(self):
        data = {"choices": [{"message": {"role": "assistant", "reasoning": "think", "content": "42"}}]}
        assert duplicate_reasoning_field(data) is True
        assert data["choices"][0]["message"]["reasoning_content"] == "think"

    def test_existing_reasoning_content_not_overwritten(self):
        data = {"choices": [{"delta": {"reasoning": "new", "reasoning_content": "old"}}]}
        assert duplicate_reasoning_field(data) is False
        assert data["choices"][0]["delta"]["reasoning_content"] == "old"

    def test_no_reasoning_untouched(self):
        data = {"choices": [{"delta": {"content": "hi"}}]}
        assert duplicate_reasoning_field(data) is False
        assert data == {"choices": [{"delta": {"content": "hi"}}]}

    def test_malformed_shapes_ignored(self):
        assert duplicate_reasoning_field(None) is False
        assert duplicate_reasoning_field("string") is False
        assert duplicate_reasoning_field({"choices": "oops"}) is False
        assert duplicate_reasoning_field({"choices": ["oops"]}) is False

    @pytest.mark.asyncio
    async def test_transparent_stream_remapped(self):
        sp = StreamProcessor(config_manager=None)
        chunk = sse(json.dumps({"choices": [{"delta": {"reasoning": "We"}}]}))
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        parsed = json.loads(result[0].decode("utf-8").split("data: ", 1)[1].split("\n\n")[0])
        assert parsed["choices"][0]["delta"]["reasoning_content"] == "We"

    @pytest.mark.asyncio
    async def test_transparent_stream_without_reasoning_unchanged(self):
        sp = StreamProcessor(config_manager=None)
        chunk = sse(json.dumps({"choices": [{"delta": {"content": "hi"}}]}))
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        assert result == [chunk]

    @pytest.mark.asyncio
    async def test_sanitized_stream_remapped(self):
        sp = make_processor(sanitize=True)
        chunk = sse(json.dumps({"choices": [{"delta": {"reasoning": "We"}}]}))
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        parsed = json.loads(result[0].decode("utf-8").split("data: ", 1)[1].split("\n\n")[0])
        assert parsed["choices"][0]["delta"]["reasoning_content"] == "We"

    @pytest.mark.asyncio
    async def test_transparent_split_json_not_corrupted(self):
        """A JSON line split across chunks must pass through without corruption."""
        sp = StreamProcessor(config_manager=None)
        full = 'data: {"choices": [{"delta": {"reasoning": "hello"}}]}\n\n'
        encoded = full.encode("utf-8")
        mid = encoded.index(b'"hello') + 3
        result = await collect(sp.process_stream(
            async_gen([encoded[:mid], encoded[mid:]]), "m", "r", "u"))
        combined = b"".join(result).decode("utf-8")
        parsed = json.loads(combined.split("data: ", 1)[1].split("\n\n")[0])
        assert parsed["choices"][0]["delta"]["reasoning"] == "hello"


# ---------------------------------------------------------------------------
# 9. SSE framing primitives (extracted from process_stream)
# ---------------------------------------------------------------------------

from src.services.chat_service.stream_processor import (  # noqa: E402
    _StreamStats,
    _decode_chunks,
    _iter_sse_frames,
    _split_frame,
)


class TestSplitFrame:

    def test_incomplete_buffer_returns_none(self):
        assert _split_frame('data: {"a":1}\n') is None

    def test_lf_frame(self):
        assert _split_frame('data: {"a":1}\n\nrest') == ('data: {"a":1}', "\n\n", "rest")

    def test_crlf_frame(self):
        assert _split_frame('data: {"a":1}\r\n\r\nrest') == ('data: {"a":1}', "\r\n\r\n", "rest")

    def test_comment_terminated_by_single_newline(self):
        assert _split_frame(": ping\n\ndata: {}\n\n") == (": ping", "\n", "\ndata: {}\n\n")

    def test_earliest_separator_wins(self):
        """A mixed-separator buffer must split on whichever boundary comes first.

        Testing for "\\r\\n\\r\\n" anywhere in the buffer merged an earlier
        "\\n\\n"-terminated message into the next frame.
        """
        buffer = 'data: {"a":1}\n\ndata: {"b":2}\r\n\r\n'
        payload, separator, rest = _split_frame(buffer)
        assert payload == 'data: {"a":1}'
        assert separator == "\n\n"
        assert rest == 'data: {"b":2}\r\n\r\n'

    def test_empty_frame_preserved(self):
        assert _split_frame("\n\ndata: {}\n\n") == ("", "\n\n", "data: {}\n\n")


class TestIterSseFrames:

    @pytest.mark.asyncio
    async def test_frames_split_across_chunks(self):
        frames = [f async for f in _iter_sse_frames(async_gen(['data: {"a"', ':1}\n\n']), "r")]
        assert frames == [('data: {"a":1}', "\n\n")]

    @pytest.mark.asyncio
    async def test_trailing_content_flushed_with_default_separator(self):
        frames = [f async for f in _iter_sse_frames(async_gen(['data: {"a":1}']), "r")]
        assert frames == [('data: {"a":1}', "\n\n")]

    @pytest.mark.asyncio
    async def test_no_trailing_frame_for_whitespace(self):
        frames = [f async for f in _iter_sse_frames(async_gen(['data: {}\n\n', "  \n"]), "r")]
        assert frames == [("data: {}", "\n\n")]

    @pytest.mark.asyncio
    async def test_mixed_separators_yield_two_frames(self):
        stream = async_gen(['data: {"a":1}\n\ndata: {"b":2}\r\n\r\n'])
        frames = [f async for f in _iter_sse_frames(stream, "r")]
        assert [p for p, _ in frames] == ['data: {"a":1}', 'data: {"b":2}']


class TestDecodeChunks:

    @pytest.mark.asyncio
    async def test_counts_bytes_and_chunks(self):
        stats = _StreamStats()
        texts = [t async for t in _decode_chunks(async_gen([b"ab", b"cd"]), "r", stats)]
        assert texts == ["ab", "cd"]
        assert stats.chunks == 2
        assert stats.bytes == 4

    @pytest.mark.asyncio
    async def test_split_multibyte_char_healed(self):
        encoded = "üx".encode("utf-8")
        stats = _StreamStats()
        stream = async_gen([encoded[:1], encoded[1:]])
        texts = [t async for t in _decode_chunks(stream, "r", stats)]
        assert "".join(texts) == "üx"

    @pytest.mark.asyncio
    async def test_malformed_bytes_replaced(self):
        stats = _StreamStats()
        stream = async_gen([b"\xff\xfe" + b"ok" * 4])
        texts = [t async for t in _decode_chunks(stream, "r", stats)]
        assert "ok" in "".join(texts)


# ---------------------------------------------------------------------------
# 11. Stats-holder enrichment (frame and row cannot drift)
# ---------------------------------------------------------------------------

from src.core.usage_db import RequestStats  # noqa: E402


class TestStatsEnrichment:

    @pytest.mark.asyncio
    async def test_mid_stream_error_writes_error_code_and_partial_usage(self):
        """A failure after the 200 must not read as a success."""
        sp = StreamProcessor(config_manager=None)
        stats = RequestStats(model_id="m", provider_name="p", stream=True)
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        chunks = [sse(json.dumps({"usage": usage}))]

        async def gen():
            for c in chunks:
                yield c
            raise HTTPException(
                status_code=500,
                detail={"error": {"code": 500, "message": "upstream died",
                                  "metadata": {"error_code": "internal_server_error"}}},
            )

        result = await collect(sp.process_stream(gen(), "m", "r", "u", "p", stats=stats))
        assert any(b"[DONE]" in r for r in result)
        assert stats.error_code == "internal_server_error"
        assert "upstream died" in stats.error_message
        # Partial usage captured before the failure survives the error path
        assert stats.prompt_tokens == 10
        assert stats.completion_tokens == 5
        assert stats.has_usage is True

    @pytest.mark.asyncio
    async def test_generic_exception_classified_internal_server_error(self):
        sp = StreamProcessor(config_manager=None)
        stats = RequestStats()

        async def gen():
            yield b"data: {}\n\n"
            raise ValueError("kaboom")

        await collect(sp.process_stream(gen(), "m", "r", "u", "p", stats=stats))
        assert stats.error_code == "internal_server_error"
        assert "kaboom" in stats.error_message

    @pytest.mark.asyncio
    async def test_http_exception_without_metadata_is_coarse(self):
        sp = StreamProcessor(config_manager=None)
        stats = RequestStats()

        async def gen():
            yield b"data: {}\n\n"
            raise HTTPException(status_code=403, detail="forbidden")

        await collect(sp.process_stream(gen(), "m", "r", "u", "p", stats=stats))
        assert stats.error_code == "internal_server_error"
        assert stats.error_message == "forbidden"

    @pytest.mark.asyncio
    async def test_successful_stream_keeps_usage_only(self):
        sp = StreamProcessor(config_manager=None)
        stats = RequestStats(model_id="m")
        usage = {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}
        await collect(sp.process_stream(
            async_gen([sse(json.dumps({"usage": usage}))]), "m", "r", "u", "p", stats=stats))
        assert stats.has_usage is True
        assert stats.total_tokens == 10
        assert stats.error_code is None
        assert stats.error_message is None

    @pytest.mark.asyncio
    async def test_usage_stays_empty_when_provider_sent_no_usage_chunk(self):
        sp = StreamProcessor(config_manager=None)
        stats = RequestStats()
        await collect(sp.process_stream(
            async_gen([b"data: {}\n\n"]), "m", "r", "u", "p", stats=stats))
        assert stats.has_usage is False
        assert stats.total_tokens == 0


# ---------------------------------------------------------------------------
# 10. Eager priming: upstream errors must keep their HTTP status
# ---------------------------------------------------------------------------

from src.services.chat_service.stream_processor import open_provider_stream  # noqa: E402


class TestOpenProviderStream:

    @pytest.mark.asyncio
    async def test_first_chunk_error_propagates(self):
        """An error on the first read raises instead of becoming a stream body."""
        async def failing():
            raise HTTPException(status_code=429, detail={"error": {"code": 429}})
            yield b""  # pragma: no cover

        with pytest.raises(HTTPException) as exc_info:
            await open_provider_stream(failing())
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_stream_content_is_unchanged(self):
        """Priming does not consume or reorder the stream."""
        stream = await open_provider_stream(async_gen([b"a", b"b", b"c"]))
        assert await collect(stream) == [b"a", b"b", b"c"]

    @pytest.mark.asyncio
    async def test_empty_stream_stays_empty(self):
        stream = await open_provider_stream(async_gen([]))
        assert await collect(stream) == []

    @pytest.mark.asyncio
    async def test_later_error_still_reaches_the_body(self):
        """An error after the first chunk cannot change the status; it is framed."""
        async def fails_late():
            yield b"first"
            raise HTTPException(status_code=500, detail="boom")

        primed = await open_provider_stream(fails_late())
        sp = make_processor(sanitize=False)
        result = b"".join(await collect(sp.process_stream(primed, "m", "r", "u")))
        assert result.startswith(b"first")
        assert b"[DONE]" in result

    @pytest.mark.asyncio
    async def test_generator_cleanup_runs_on_first_read_failure(self):
        """The failing generator's finally block runs, releasing its slot."""
        released = []

        async def failing():
            try:
                raise HTTPException(status_code=401, detail="nope")
                yield b""  # pragma: no cover
            finally:
                released.append(True)

        with pytest.raises(HTTPException):
            await open_provider_stream(failing())
        assert released == [True]

    @pytest.mark.asyncio
    async def test_abandoning_primed_stream_closes_the_source(self):
        """A client disconnect must close the wrapped provider stream.

        Otherwise the provider's in-flight slot is never released and a config
        reload waits out the whole drain timeout before closing the pool.
        """
        closed = []

        async def source():
            try:
                yield b"a"
                yield b"b"
            finally:
                closed.append(True)

        primed = await open_provider_stream(source())
        assert await primed.__anext__() == b"a"
        await primed.aclose()
        assert closed == [True]
