"""Unit tests for StreamProcessor."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.services.chat_service.stream_processor import StreamProcessor
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
        assert sp.should_sanitize is False
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
# 7. _determine_sanitization_status
# ---------------------------------------------------------------------------

class TestDetermineSanitizationStatus:

    def test_no_config_manager(self):
        sp = StreamProcessor(config_manager=None)
        assert sp.should_sanitize is False

    def test_config_true(self):
        cm = MagicMock()
        cm.should_sanitize_messages = True
        sp = StreamProcessor(config_manager=cm)
        assert sp.should_sanitize is True

    def test_config_false(self):
        cm = MagicMock()
        cm.should_sanitize_messages = False
        sp = StreamProcessor(config_manager=cm)
        assert sp.should_sanitize is False

    def test_config_raises(self):
        cm = MagicMock()
        type(cm).should_sanitize_messages = property(lambda self: (_ for _ in ()).throw(RuntimeError("broken")))
        sp = StreamProcessor(config_manager=cm)
        assert sp.should_sanitize is False


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
