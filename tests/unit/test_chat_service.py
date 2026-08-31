"""Unit tests for src/services/chat_service/chat_service.py — body decoding and happy paths."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from src.core.context import AuthContext, RequestContext
from src.core.usage_db import RequestStats
from src.services.chat_service.chat_service import ChatService


def _make_auth_context():
    """AuthContext matching what auth.get_api_key builds."""
    return AuthContext(allowed_models=[], allowed_endpoints=[])


def _service() -> ChatService:
    return ChatService(MagicMock(), MagicMock())


def _request_raising(exc: Exception):
    request = MagicMock()
    request.state = SimpleNamespace(
        request_context=RequestContext(request_id="req-chat", project_name="proj")
    )
    request.json = AsyncMock(side_effect=exc)
    return request


class TestInvalidBody:

    @pytest.mark.asyncio
    async def test_invalid_utf8_body_raises_400_not_500(self):
        """Starlette's request.json() raises UnicodeDecodeError on non-UTF-8 bytes —
        json.JSONDecodeError does not cover it; the client must get a 400 envelope."""
        request = _request_raising(
            UnicodeDecodeError("utf-8", b"\xff\xfe", 0, 1, "invalid start byte")
        )

        with pytest.raises(HTTPException) as exc_info:
            await _service().chat_completions(request, _make_auth_context())

        assert exc_info.value.status_code == 400
        assert "valid JSON body" in exc_info.value.detail["error"]["message"]

    @pytest.mark.asyncio
    async def test_malformed_json_still_400(self):
        request = _request_raising(json.JSONDecodeError("Expecting value", "{not", 0))

        with pytest.raises(HTTPException) as exc_info:
            await _service().chat_completions(request, _make_auth_context())

        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Happy paths with a stub provider (no network)
# ---------------------------------------------------------------------------

class _StubProvider:
    """Provider double: records dispatch, returns canned bodies."""

    identity = None  # no identity profile → identity_headers stay None

    def __init__(self, stream_frames=None):
        self.chat_calls: list[tuple[dict, str]] = []
        self.stream_calls: list[tuple[dict, str]] = []
        self.stream_frames = stream_frames or []

    async def chat_completions(self, request_body, provider_model_name, model_config,
                               request_id="unknown", extra_headers=None):
        self.chat_calls.append((dict(request_body), provider_model_name))
        return {
            "id": "chatcmpl-1", "object": "chat.completion", "created": 1,
            "model": request_body["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
        }

    def chat_completions_stream(self, request_body, provider_model_name, model_config,
                                request_id="unknown", extra_headers=None):
        self.stream_calls.append((dict(request_body), provider_model_name))

        async def gen():
            for frame in self.stream_frames:
                yield frame

        return gen()


def _happy_service(provider: _StubProvider) -> ChatService:
    cm = MagicMock()
    cm.get_config.return_value = {
        "models": {"chat/model-a": {"provider": "prov-a",
                                    "provider_model_name": "upstream-a"}},
        "providers": {"prov-a": {"base_url": "http://upstream.invalid"}},
    }
    return ChatService(cm, MagicMock())


def _happy_request(body: dict):
    request = MagicMock()
    request.state = SimpleNamespace(
        request_context=RequestContext(request_id="req-chat", project_name="proj"),
        request_stats=RequestStats(endpoint="chat"),
    )
    request.json = AsyncMock(return_value=body)
    request.headers = {}
    return request


def _patch_provider(provider):
    async def _get_instance(name):
        return provider
    return patch("src.services.base.get_provider_instance", side_effect=_get_instance)


class TestChatHappyPaths:

    @pytest.mark.asyncio
    async def test_non_stream_returns_provider_json_and_enriches_stats(self):
        provider = _StubProvider()
        request = _happy_request({"model": "chat/model-a",
                                  "messages": [{"role": "user", "content": "ping"}]})

        with _patch_provider(provider):
            response = await _happy_service(provider).chat_completions(
                request, _make_auth_context())

        assert isinstance(response, JSONResponse)
        body = json.loads(response.body)
        assert body["choices"][0]["message"]["content"] == "hi"
        # the service dispatches with the mapped provider_model_name; body
        # rewriting is the provider's job (_apply_model_config), not the service's
        assert provider.chat_calls[0][0]["model"] == "chat/model-a"
        assert provider.chat_calls[0][1] == "upstream-a"
        # usage from the provider body enriched the per-request stats holder
        stats = request.state.request_stats
        assert stats.has_usage is True
        assert stats.prompt_tokens == 3
        assert stats.provider_name == "prov-a"
        assert stats.model_id == "chat/model-a"
        assert stats.stream is False

    @pytest.mark.asyncio
    async def test_stream_returns_sse_passthrough(self):
        frames = [
            b'data: {"choices":[{"delta":{"content":"he"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"y"}}]}\n\n',
            b'data: [DONE]\n\n',
        ]
        provider = _StubProvider(stream_frames=frames)
        request = _happy_request({"model": "chat/model-a",
                                  "messages": [{"role": "user", "content": "ping"}],
                                  "stream": True})

        with _patch_provider(provider):
            response = await _happy_service(provider).chat_completions(
                request, _make_auth_context())

        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"
        chunks = [chunk async for chunk in response.body_iterator]
        assert chunks == frames
        # stream flag was set on the stats holder before dispatch
        assert request.state.request_stats.stream is True
        assert provider.stream_calls[0][1] == "upstream-a"
