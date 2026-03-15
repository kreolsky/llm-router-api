import httpx
import json
from typing import Dict, Any
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi import HTTPException, status

from .base import BaseProvider
from ..utils.deep_merge import deep_merge
from ..core.error_handling import ErrorHandler, ErrorContext
from ..core.logging import logger

class AnthropicProvider(BaseProvider):
    def __init__(self, config: Dict[str, Any], client: httpx.AsyncClient, config_manager=None):
        super().__init__(config, client, config_manager)
        # Anthropic specific headers
        for key, value in config.get("headers", {}).items():
            self.headers[key] = value

    async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        """
        Handle chat completions requests to Anthropic API.
        
        This method transforms the OpenAI-compatible request to Anthropic's format,
        which requires 'model', 'messages', and 'max_tokens' at the top level.
        It delegates to the base provider's unified request methods for consistent
        error handling and logging.
        
        Args:
            request_body: OpenAI-compatible request body
            provider_model_name: The model name to use for this provider
            model_config: Provider-specific model configuration including options
        
        Returns:
            For streaming: StreamingResponse with SSE content
            For non-streaming: JSONResponse with Anthropic's response format
        """
        # Anthropic API expects 'model' and 'messages' at the top level
        # and 'max_tokens' is required.
        # It also uses 'system' for system prompts, not part of messages array.
        
        # Build anthropic request with optional fields
        anthropic_request = {
            "model": provider_model_name,
            "messages": request_body.get("messages", []),
            "max_tokens": request_body.get("max_tokens", 1024),
            "stream": request_body.get("stream", False)
        }
        
        # Add optional fields if present
        for field in ["temperature", "system"]:
            if field in request_body:
                anthropic_request[field] = request_body[field]

        if options := model_config.get("options"):
            anthropic_request = deep_merge(anthropic_request, options)

        # Stream or non-streaming request
        if anthropic_request["stream"]:
            return await self._stream_request(self.client, "/messages", anthropic_request)
        
        # Use config_manager.anthropic_timeout if available
        anthropic_timeout = self._get_timeout("anthropic_timeout", 600)
        
        # Use the base provider's unified request method
        response_json = await self._make_request(
            method="POST",
            path="/messages",
            request_body=anthropic_request,
            timeout=anthropic_timeout,
            request_id=request_body.get("request_id", "unknown")
        )
        
        # Anthropic returns JSON, wrap in JSONResponse for consistency
        return JSONResponse(content=response_json)
