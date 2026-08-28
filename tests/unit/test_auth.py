"""Unit tests for src/core/auth.py — non-ASCII bearer tokens yield 401, not 500.

Driven through raw ASGI with raw header bytes: httpx cannot even express a
non-ASCII header value (it encodes as ASCII), while any real client (curl)
can put arbitrary bytes on the wire — Starlette decodes them latin-1, and the
token reaches get_api_key as a non-ASCII str.
"""

import json

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request

from src.api.main import custom_http_exception_handler
from src.core.auth import get_api_key
from src.core.context import AuthContext, request_context


def _config_manager_with_keys(keys: dict[str, str]):
    class _CM:
        def get_config(self):
            return {"user_keys": {name: {"api_key": key} for name, key in keys.items()}}
    return _CM()


@pytest.fixture
def app():
    """Minimal app wiring the REAL HTTPException handler so the envelope shape is asserted."""
    application = FastAPI()
    application.state.config_manager = _config_manager_with_keys({"lab": "nnp-v1-valid-key"})
    application.add_exception_handler(HTTPException, custom_http_exception_handler)

    @application.get("/check")
    async def check(request: Request, auth_context: AuthContext = Depends(get_api_key)):
        # AuthContext carries grants only; the resolved project name is read
        # from the request context it now solely owns.
        return {"user": request_context(request).user_id}

    return application


async def _drive(app, headers: list[tuple[bytes, bytes]]) -> tuple[int, dict, bytes | None]:
    """Send GET /check through raw ASGI; return (status, body-bytes, raised-or-None)."""
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "GET", "scheme": "http",
        "path": "/check", "raw_path": b"/check", "query_string": b"",
        "root_path": "", "headers": headers,
        "client": ("127.0.0.1", 123), "server": ("testserver", 80), "state": {},
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    raised = None
    try:
        await app(scope, receive, send)
    except Exception as e:  # noqa: BLE001 — the driver must observe ServerErrorMiddleware's re-raise
        raised = e

    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, body, raised


class TestNonAsciiBearer:

    @pytest.mark.asyncio
    async def test_non_ascii_bearer_is_401_envelope_not_500(self, app):
        """compare_digest on a non-ASCII str raises TypeError today — must be 401 + envelope."""
        status, body, _ = await _drive(app, [(b"authorization", b"Bearer nnp-v1-\xbf\xbf")])

        assert status == 401
        envelope = json.loads(body)
        assert envelope["error"]["code"] == 401
        assert envelope["error"]["metadata"]["error_code"] == "invalid_api_key"

    @pytest.mark.asyncio
    async def test_ascii_invalid_key_still_401(self, app):
        status, body, _ = await _drive(app, [(b"authorization", b"Bearer nnp-v1-wrong")])
        assert status == 401
        assert json.loads(body)["error"]["code"] == 401

    @pytest.mark.asyncio
    async def test_valid_key_passes(self, app):
        status, body, raised = await _drive(app, [(b"authorization", b"Bearer nnp-v1-valid-key")])
        assert raised is None
        assert status == 200
        assert json.loads(body) == {"user": "lab"}

    @pytest.mark.asyncio
    async def test_missing_key_401(self, app):
        status, body, _ = await _drive(app, [])
        assert status == 401
        assert json.loads(body)["error"]["metadata"]["error_code"] == "missing_api_key"
