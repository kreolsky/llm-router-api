"""Chat completion orchestrator: validation, provider dispatch, streaming."""

import httpx
import inspect
import json
from typing import Dict, Any, Tuple
from fastapi import HTTPException, status, Request
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

    def __init__(self, config_manager: ConfigManager, httpx_client: httpx.AsyncClient, model_service: ModelService):
        super().__init__(config_manager, httpx_client)
        self.model_service = model_service
        self.stream_processor = StreamProcessor(config_manager)
    
    async def chat_completions(self, request: Request, auth_data: Tuple[str, str, list, list]) -> Any:
        """Process a chat completion request, returning StreamingResponse or JSONResponse."""
        context_dict = self._get_request_context(request, auth_data)
        request_id = context_dict["request_id"]
        user_id = context_dict["user_id"]

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

        logger.info(
            f"Request: Chat Completion | model={requested_model}",
            request_id=request_id,
            user_id=user_id,
            model_id=requested_model
        )

        error_ctx = dict(request_id=request_id, user_id=user_id, model_id=requested_model)

        model_config, provider_name, provider_model_name, provider_config = \
            self._validate_and_get_config(requested_model, auth_data, **error_ctx)

        provider_instance = self._get_provider(provider_config, **error_ctx)
        
        try:
            with logger.request_context(
                operation="Chat Completion",
                request_id=request_id,
                user_id=user_id,
                model_id=requested_model,
                provider_name=provider_name
            ):
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
                
                response_data = await provider_instance.chat_completions(request_body, provider_model_name, model_config)
                
                if inspect.isasyncgen(response_data):
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
                            response_data, requested_model, request_id, user_id
                        ),
                        media_type="text/event-stream",
                        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
                    )
                else:
                    self._log_service_data(
                        title="Chat Completion Response JSON",
                        data=response_data,
                        request_id=request_id,
                        component="chat_service",
                        data_flow="from_provider"
                    )
                    
                    return JSONResponse(content=response_data)
            
        except HTTPException as e:
            raise e
        except Exception as e:
            raise create_error(ErrorType.INTERNAL_SERVER_ERROR, original_exception=e, error_details=str(e), **error_ctx)