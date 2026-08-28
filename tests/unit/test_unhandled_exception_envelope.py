"""The app-level Exception handler must answer unhandled errors in the OpenRouter envelope.

Driven through raw ASGI, not TestClient: Starlette's ServerErrorMiddleware
re-raises after the handler responds, and TestClient(raise_server_exceptions=
False) swallows that re-raise — hiding double-send bugs.
"""

import json

import pytest
from fastapi import Request

from src.api.main import app

_BOMB_PATH = "/health/__boom__"


async def _drive(app, method: str, path: str):
    """Run one request through the ASGI app; return (sent-messages, raised-or-None)."""
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": method, "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": b"",
        "root_path": "", "headers": [(b"host", b"testserver")],
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
    except Exception as e:  # noqa: BLE001 — the driver must observe the re-raise
        raised = e
    return sent, raised


@pytest.fixture
def bomb_route():
    """Temporarily add a route that raises an unhandled RuntimeError.

    Mounted under /health so the request-logging middleware skips usage-row
    recording (no DB is initialized in this unit test).
    """
    async def bomb(request: Request):
        raise RuntimeError("boom-unhandled")

    app.add_api_route(_BOMB_PATH, bomb, methods=["GET"])
    yield
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != _BOMB_PATH]


class TestUnhandledExceptionEnvelope:

    @pytest.mark.asyncio
    async def test_unhandled_error_returns_openrouter_envelope_single_response(self, bomb_route):
        sent, raised = await _drive(app, "GET", _BOMB_PATH)

        starts = [m for m in sent if m["type"] == "http.response.start"]
        assert len(starts) == 1, f"expected exactly one response.start, got {len(starts)}"
        assert starts[0]["status"] == 500

        headers = dict(starts[0].get("headers", []))
        assert headers.get(b"content-type", b"").startswith(b"application/json")

        body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
        envelope = json.loads(body)
        assert envelope["error"]["code"] == 500
        assert isinstance(envelope["error"]["message"], str) and envelope["error"]["message"]

        # Starlette always re-raises after the handler responds; the response
        # above was still sent exactly once.
        assert isinstance(raised, RuntimeError)
