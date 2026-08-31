"""Pure ASGI request/response logging middleware with request ID injection.

Uses raw ASGI protocol instead of BaseHTTPMiddleware to avoid response
buffering that adds latency to SSE streaming responses.

ARCH: this middleware is the SINGLE usage-stats writer. It creates a
RequestStats holder in scope state next to the RequestContext, services only
enrich the holder, and exactly one flush (one INSERT) runs in a ``finally``
at the end of the request lifecycle. The flush must be in ``finally``:
Starlette's ServerErrorMiddleware sits outside user middleware, so an
unhandled exception — and a CancelledError from a client disconnecting
mid-stream — propagates past any ``except`` here; code after the app call
would silently lose exactly the 500s and aborted streams the stats exist to
record.
"""
# SYSTEM: request-logging — pure-ASGI request id + Incoming/Outgoing bookends
import json
import os
import time

from starlette.requests import Request

from ..core.context import RequestContext
from ..core.logging import logger
from ..core.usage_db import RequestStats, schedule_flush
from ..utils.client_address import client_host

# Paths that never produce a usage row: health probe, the stats dashboard
# itself (page, JSON API and the static mount), docs and browser noise.
_SKIP_PATH_PREFIXES = ("/health", "/stat", "/docs", "/openapi.json", "/favicon.ico")

# ARCH: the endpoint name for the usage row lives ON the route decorator
# (name="chat" etc. in src/api/main.py) — the one place a new route cannot
# forget. This middleware reads scope["route"].name after the app call; the
# names are NOT derivable from handler function names because stored rows use
# legacy values (chat/embeddings/models) that historical rows group by.


class RequestLoggerMiddleware:
    """Injects RequestContext + RequestStats into scope state and logs lifecycle.

    Pure ASGI middleware — does not buffer response body, so streaming
    responses (SSE) pass through with zero additional latency per chunk.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.time()
        request_id = os.urandom(8).hex()

        # Inject typed RequestContext into scope state for downstream handlers
        state = scope.setdefault("state", {})
        state["request_context"] = RequestContext(request_id=request_id)

        method = scope.get("method", "")
        path = scope.get("path", "")
        query = scope.get("query_string", b"").decode("utf-8", errors="replace")
        url = f"{path}?{query}" if query else path

        # ARCH: per-request stats holder; enriched by services/auth, flushed
        # once below. Skipped paths (health, stats, docs) never record.
        # endpoint starts as the raw path — the route's name (set by the
        # router during the app call below) replaces it in the finally.
        should_record = not path.startswith(_SKIP_PATH_PREFIXES)
        stats: RequestStats | None = None
        if should_record:
            stats = RequestStats(
                endpoint=path,
                client_ip=client_host(Request(scope)),
            )
            state["request_stats"] = stats

        logger.info(
            f"Request: Incoming Request | method={method}",
            request_id=request_id,
            user_id="unknown",
            url=url
        )

        # Debug body logging: intercept receive to log body without consuming it
        if method in ("POST", "PUT", "PATCH") and logger.is_debug_enabled():
            body_chunks = []
            original_receive = receive

            async def buffered_receive():
                message = await original_receive()
                if message.get("type") == "http.request":
                    body_chunks.append(message.get("body", b""))
                    if not message.get("more_body", False):
                        try:
                            raw_body = b"".join(body_chunks)
                            request_body = json.loads(raw_body)
                            logger.debug_data(
                                title="Request JSON",
                                data=request_body,
                                request_id=request_id,
                                component="middleware",
                                data_flow="incoming"
                            )
                        except Exception:
                            logger.debug("Could not parse request JSON", request_id=request_id)
                return message

            receive = buffered_receive

        status_code = None

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
                # Add X-Process-Time header
                headers = list(message.get("headers", []))
                process_time = time.time() - start_time
                headers.append((b"x-process-time", str(process_time).encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:
            logger.error(
                f"Unexpected error: {str(e)}",
                request_id=request_id,
                user_id="unknown",
                status_code=500,
                exc_info=True
            )
            raise
        finally:
            # WHY finally: must run for unhandled 500s and mid-stream client
            # disconnects (CancelledError), not just clean returns. With no
            # http.response.start ever sent, the row records status 500.
            if should_record and stats is not None:
                # The route is only populated on scope AFTER the app call —
                # including its except branches and a client disconnect
                # mid-stream. A request that never resolved (404) keeps the
                # raw path it started with.
                route = scope.get("route")
                if route is not None and getattr(route, "name", None):
                    stats.endpoint = route.name
                ctx: RequestContext | None = scope.get("state", {}).get("request_context")
                project_name = ctx.user_id if ctx else "unknown"
                schedule_flush(
                    stats,
                    request_id=request_id,
                    project_name=project_name,
                    duration_ms=(time.time() - start_time) * 1000,
                    status_code=status_code if status_code else 500,
                    app_state=getattr(scope.get("app"), "state", None),
                )

        process_time = time.time() - start_time
        ctx: RequestContext = scope.get("state", {}).get("request_context")
        user_id = ctx.user_id if ctx else "unknown"

        logger.info(
            f"Response: Outgoing Response | status={status_code} | time={round(process_time * 1000)}ms",
            request_id=request_id,
            user_id=user_id
        )
