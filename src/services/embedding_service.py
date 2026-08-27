"""Embedding creation service proxying requests to configured providers."""
import json
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from ..core.error_handling import ErrorType, create_error
from ..core.logging import logger
from ..core.usage_db import request_stats
from .base import BaseService


class EmbeddingService(BaseService):

    async def create_embeddings(self, request: Request, auth_data: tuple[str, str, list, list]) -> Any:
        """Validate, dispatch, and return an embedding creation request."""
        ctx = self._get_request_context(request)
        request_id = ctx.request_id
        user_id = ctx.user_id
        
        try:
            request_body = await request.json()
        except json.JSONDecodeError:
            raise create_error(ErrorType.MISSING_REQUIRED_FIELD, field_name="valid JSON body",
                             request_id=request_id, user_id=user_id)

        requested_model = request_body.get("model")
        stats = request_stats(request)
        stats.model_id = requested_model if isinstance(requested_model, str) else ""

        error_ctx = dict(request_id=request_id, user_id=user_id, model_id=requested_model)

        self._log_service_data(
            title="Embedding Request JSON",
            data=request_body,
            request_id=request_id,
            component="embedding_service",
            data_flow="incoming"
        )

        model_config, provider_name, provider_model_name, provider_config = \
            self._validate_and_get_config(requested_model, auth_data, **error_ctx)
        stats.provider_name = provider_name

        provider_instance = await self._get_provider(provider_name, provider_config, **error_ctx)
        identity_headers = self._build_identity_headers(provider_instance, request)

        async with self._guard_service_errors(error_ctx):
            response_data = await provider_instance.embeddings(
                request_body, provider_model_name, model_config, request_id=request_id,
                extra_headers=identity_headers
            )

            self._log_service_data(
                title="Embedding Response JSON",
                data=response_data,
                request_id=request_id,
                component="embedding_service",
                data_flow="from_provider"
            )

            logger.info(
                f"Response: Embedding Creation | model={requested_model}",
                request_id=request_id,
                user_id=user_id,
                model_id=requested_model,
                token_usage={
                    "prompt_tokens": response_data.get("usage", {}).get("prompt_tokens", 0),
                    "total_tokens": response_data.get("usage", {}).get("total_tokens", 0)
                }
            )

            usage = response_data.get("usage", {})
            if usage:
                stats.set_usage(usage)

            return JSONResponse(content=response_data)
