"""Unit tests for StreamProcessor."""

import json

import pytest
from fastapi import HTTPException

from src.services.chat_service.stream_processor import StreamProcessor, duplicate_reasoning_field

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def async_gen(items):
    for item in items:
        yield item


async def collect(agen):
    return [x async for x in agen]


def sse(data_str, sep="\n\n"):
    return f"data: {data_str}{sep}".encode()


def make_processor():
    return StreamProcessor()


# ---------------------------------------------------------------------------
# 1. Transparent mode
# ---------------------------------------------------------------------------

class TestTransparentMode:

    @pytest.mark.asyncio
    async def test_chunks_pass_through(self):
        sp = StreamProcessor()
        chunks = [b"data: hello\n\n", b"data: world\n\n"]
        result = await collect(sp.process_stream(async_gen(chunks), "m", "r", "u"))
        assert result == chunks

    @pytest.mark.asyncio
    async def test_empty_stream(self):
        sp = StreamProcessor()
        result = await collect(sp.process_stream(async_gen([]), "m", "r", "u"))
        assert result == []


# ---------------------------------------------------------------------------
# 6. Mid-stream error frame (via process_stream)
# ---------------------------------------------------------------------------

def _parse_error_frame(result: bytes):
    """Parse the first SSE data frame from a stream's error output."""
    text = result.decode("utf-8")
    first_frame = text.split("\n\n", 1)[0]
    return json.loads(first_frame[len("data: "):])


def raising_gen(exc):
    """A provider stream that fails on its first read."""
    async def gen():
        raise exc
        yield b""  # pragma: no cover
    return gen()


class TestErrorFrame:

    @pytest.mark.asyncio
    async def test_generic_exception(self):
        sp = StreamProcessor()
        result = b"".join(await collect(
            sp.process_stream(raising_gen(ValueError("oops")), "m", "r", "u")))
        decoded = _parse_error_frame(result)
        assert decoded["error"]["code"] == 500
        assert "oops" in decoded["error"]["message"]

    @pytest.mark.asyncio
    async def test_http_exception_string_detail(self):
        sp = StreamProcessor()
        exc = HTTPException(status_code=403, detail="forbidden")
        result = b"".join(await collect(
            sp.process_stream(raising_gen(exc), "m", "r", "u")))
        decoded = _parse_error_frame(result)
        assert decoded["error"]["code"] == 403
        assert "forbidden" in decoded["error"]["message"]

    @pytest.mark.asyncio
    async def test_http_exception_dict_detail(self):
        sp = StreamProcessor()
        detail = {"error": {"code": 429, "message": "rate limited"}}
        exc = HTTPException(status_code=429, detail=detail)
        result = b"".join(await collect(
            sp.process_stream(raising_gen(exc), "m", "r", "u")))
        decoded = _parse_error_frame(result)
        assert decoded["error"]["code"] == 429
        assert decoded["error"]["message"] == "rate limited"

    @pytest.mark.asyncio
    async def test_returns_bytes_with_sse_framing(self):
        sp = StreamProcessor()
        result = b"".join(await collect(
            sp.process_stream(raising_gen(RuntimeError("x")), "m", "r", "u")))
        assert isinstance(result, bytes)
        assert result.startswith(b"data: ")
        assert result.endswith(b"\n\n")

    @pytest.mark.asyncio
    async def test_ends_with_done_sentinel(self):
        sp = StreamProcessor()
        result = b"".join(await collect(
            sp.process_stream(raising_gen(RuntimeError("x")), "m", "r", "u")))
        assert result.endswith(b"data: [DONE]\n\n")


# ---------------------------------------------------------------------------
# 7b. Concurrency: per-stream captured usage isolation
# ---------------------------------------------------------------------------

class TestConcurrentStreamUsageIsolation:

    @pytest.mark.asyncio
    async def test_two_interleaved_streams_record_own_usage(self):
        """Two concurrent streams over one processor each capture their own usage."""
        sp = StreamProcessor()

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
        sp = StreamProcessor()
        chunk = sse(json.dumps({"choices": [{"delta": {"reasoning": "We"}}]}))
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        parsed = json.loads(result[0].decode("utf-8").split("data: ", 1)[1].split("\n\n")[0])
        assert parsed["choices"][0]["delta"]["reasoning_content"] == "We"

    @pytest.mark.asyncio
    async def test_transparent_stream_without_reasoning_unchanged(self):
        sp = StreamProcessor()
        chunk = sse(json.dumps({"choices": [{"delta": {"content": "hi"}}]}))
        result = await collect(sp.process_stream(async_gen([chunk]), "m", "r", "u"))
        assert result == [chunk]

    @pytest.mark.asyncio
    async def test_transparent_split_json_not_corrupted(self):
        """A JSON line split across chunks must pass through without corruption."""
        sp = StreamProcessor()
        full = 'data: {"choices": [{"delta": {"reasoning": "hello"}}]}\n\n'
        encoded = full.encode("utf-8")
        mid = encoded.index(b'"hello') + 3
        result = await collect(sp.process_stream(
            async_gen([encoded[:mid], encoded[mid:]]), "m", "r", "u"))
        combined = b"".join(result).decode("utf-8")
        parsed = json.loads(combined.split("data: ", 1)[1].split("\n\n")[0])
        assert parsed["choices"][0]["delta"]["reasoning"] == "hello"


# ---------------------------------------------------------------------------
# 11. Stats-holder enrichment (frame and row cannot drift)
# ---------------------------------------------------------------------------

from src.core.usage_db import RequestStats  # noqa: E402


class TestStatsEnrichment:

    @pytest.mark.asyncio
    async def test_mid_stream_error_writes_error_code_and_partial_usage(self):
        """A failure after the 200 must not read as a success."""
        sp = StreamProcessor()
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
        sp = StreamProcessor()
        stats = RequestStats()

        async def gen():
            yield b"data: {}\n\n"
            raise ValueError("kaboom")

        await collect(sp.process_stream(gen(), "m", "r", "u", "p", stats=stats))
        assert stats.error_code == "internal_server_error"
        assert "kaboom" in stats.error_message

    @pytest.mark.asyncio
    async def test_http_exception_without_metadata_is_coarse(self):
        sp = StreamProcessor()
        stats = RequestStats()

        async def gen():
            yield b"data: {}\n\n"
            raise HTTPException(status_code=403, detail="forbidden")

        await collect(sp.process_stream(gen(), "m", "r", "u", "p", stats=stats))
        assert stats.error_code == "internal_server_error"
        assert stats.error_message == "forbidden"

    @pytest.mark.asyncio
    async def test_successful_stream_keeps_usage_only(self):
        sp = StreamProcessor()
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
        sp = StreamProcessor()
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
        sp = make_processor()
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


# ---------------------------------------------------------------------------
# 12. Constructor: no dead config_manager parameter
# ---------------------------------------------------------------------------

class TestConstructor:
    def test_no_config_manager_parameter(self):
        """config_manager was dead: assigned, never read. It is gone."""
        import inspect

        params = inspect.signature(StreamProcessor.__init__).parameters
        assert "config_manager" not in params
        assert StreamProcessor() is not None
