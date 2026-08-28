"""Unit tests for src/services/chat_service/chat_service.py — request body decoding."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.core.context import AuthContext, RequestContext
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
        import json

        request = _request_raising(json.JSONDecodeError("Expecting value", "{not", 0))

        with pytest.raises(HTTPException) as exc_info:
            await _service().chat_completions(request, _make_auth_context())

        assert exc_info.value.status_code == 400
