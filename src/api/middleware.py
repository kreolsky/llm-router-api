"""Pure ASGI request/response logging middleware with request ID injection.

Uses raw ASGI protocol instead of BaseHTTPMiddleware to avoid response
buffering that adds latency to SSE streaming responses.
"""
import time
import os
import json
from ..core.logging import logger


class RequestLoggerMiddleware:
    """Injects request_id into scope state and logs request/response lifecycle.

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

        # Inject request_id into scope state so request.state.request_id works downstream
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id

        method = scope.get("method", "")
        path = scope.get("path", "")
        query = scope.get("query_string", b"").decode("utf-8", errors="replace")
        url = f"{path}?{query}" if query else path

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

        process_time = time.time() - start_time
        user_id = scope.get("state", {}).get("project_name", "unknown")

        logger.info(
            f"Response: Outgoing Response | status={status_code} | time={round(process_time * 1000)}ms",
            request_id=request_id,
            user_id=user_id
        )