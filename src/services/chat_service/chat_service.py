"""Chat completion orchestrator: validation, provider dispatch, streaming."""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from ...core.context import AuthContext
from ...core.logging import logger
from ...services.base import BaseService
from .stream_processor import duplicate_reasoning_field, open_provider_stream, process_stream


class ChatService(BaseService):
    """Coordinates chat completion requests across providers with streaming support."""

    async def chat_completions(self, request: Request, auth_context: AuthContext) -> Any:
        """Process a chat completion request, returning StreamingResponse or JSONResponse."""
        prepared = await self._prepare_dispatch(
            request, auth_context,
            component="chat_service", log_title="Chat Completion Request JSON",
        )

        async with self._guard_service_errors(prepared.error_ctx):
            if prepared.request_body.get("stream", False):
                prepared.stats.stream = True
                provider_stream = prepared.provider.chat_completions_stream(
                    prepared.request_body, prepared.provider_model_name, prepared.model_config,
                    request_id=prepared.request_id, extra_headers=prepared.identity_headers
                )
                # Surface an upstream failure as a real HTTP status instead of a
                # 200 carrying an SSE error frame (see open_provider_stream).
                provider_stream = await open_provider_stream(provider_stream)
                logger.debug_data(
                    title="Streaming Response Started",
                    data={
                        "streaming": True,
                        "model": prepared.requested_model,
                        "request_id": prepared.request_id
                    },
                    request_id=prepared.request_id,
                    component="chat_service",
                    data_flow="from_provider"
                )

                return StreamingResponse(
                    process_stream(
                        provider_stream, prepared.requested_model, prepared.request_id,
                        prepared.user_id, prepared.provider_name, stats=prepared.stats
                    ),
                    media_type="text/event-stream",
                    headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
                )

            response_data = await prepared.provider.chat_completions(
                prepared.request_body, prepared.provider_model_name, prepared.model_config,
                request_id=prepared.request_id, extra_headers=prepared.identity_headers
            )

            duplicate_reasoning_field(response_data)

            logger.debug_data(
                title="Chat Completion Response JSON",
                data=response_data,
                request_id=prepared.request_id,
                component="chat_service",
                data_flow="from_provider"
            )

            usage = response_data.get("usage", {})
            if usage:
                prepared.stats.set_usage(usage)

            return JSONResponse(content=response_data)
