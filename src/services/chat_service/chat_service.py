"""Chat completion orchestrator: validation, provider dispatch, streaming."""

import json
import time
from typing import Any, Tuple
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from ...core.config_manager import ConfigManager
from ...services.model_service import ModelService
from ...core.logging import logger
from ...core.sanitizer import MessageSanitizer
from ...core.error_handling import ErrorType, create_error
from ...services.base import BaseService
from .stream_processor import StreamProcessor


class ChatService(BaseService):
    """Coordinates chat completion requests across providers with streaming support."""

    def __init__(self, config_manager: ConfigManager, model_service: ModelService):
        super().__init__(config_manager)
        self.model_service = model_service
        self.stream_processor = StreamProcessor(config_manager)
    
    async def chat_completions(self, request: Request, auth_data: Tuple[str, str, list, list]) -> Any:
        """Process a chat completion request, returning StreamingResponse or JSONResponse."""
        context_dict = self._get_request_context(request)
        request_id = context_dict["request_id"]
        user_id = context_dict["user_id"]

        start_time = time.time()

        try:
            request_body = await request.json()
        except json.JSONDecodeError:
            raise create_error(ErrorType.MISSING_REQUIRED_FIELD, field_name="valid JSON body",
                             request_id=request_id, user_id=user_id)

        requested_model = request_body.get("model")

        self._log_service_data(
            title="Chat Completion Request JSON",
            data=request_body,
            request_id=request_id,
            component="chat_service",
            data_flow="incoming"
        )

        error_ctx = dict(request_id=request_id, user_id=user_id, model_id=requested_model)

        model_config, provider_name, provider_model_name, provider_config = \
            self._validate_and_get_config(requested_model, auth_data, **error_ctx)

        provider_instance = await self._get_provider(provider_name, provider_config, **error_ctx)

        async with self._guard_service_errors(error_ctx):
            if self.config_manager.should_sanitize_messages:
                messages = request_body.get("messages", [])
                if messages:
                    original_count = len(messages)
                    sanitized_messages = MessageSanitizer.sanitize_messages(messages, enabled=True)
                    request_body["messages"] = sanitized_messages

                    if len(sanitized_messages) != original_count:
                        logger.info(
                            f"Sanitized {original_count} messages to {len(sanitized_messages)}",
                            request_id=request_id,
                            user_id=user_id
                        )

            if request_body.get("stream", False):
                provider_stream = provider_instance.chat_completions_stream(
                    request_body, provider_model_name, model_config, request_id=request_id
                )
                self._log_service_data(
                    title="Streaming Response Started",
                    data={
                        "streaming": True,
                        "model": requested_model,
                        "request_id": request_id
                    },
                    request_id=request_id,
                    component="chat_service",
                    data_flow="from_provider"
                )

                return StreamingResponse(
                    self.stream_processor.process_stream(
                        provider_stream, requested_model, request_id, user_id, provider_name
                    ),
                    media_type="text/event-stream",
                    headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
                )

            response_data = await provider_instance.chat_completions(
                request_body, provider_model_name, model_config, request_id=request_id
            )

            self._log_service_data(
                title="Chat Completion Response JSON",
                data=response_data,
                request_id=request_id,
                component="chat_service",
                data_flow="from_provider"
            )

            usage = response_data.get("usage", {})
            if usage:
                from ...core.usage_db import schedule_chat_usage
                schedule_chat_usage(
                    usage,
                    project_name=user_id,
                    model_id=requested_model,
                    request_id=request_id,
                    provider_name=provider_name,
                    start_time=start_time,
                )

            return JSONResponse(content=response_data)