"""Anthropic provider translating OpenAI-format requests to Messages API."""
import httpx
from typing import Dict, Any
from fastapi.responses import JSONResponse

from .base import BaseProvider
from ..utils.deep_merge import deep_merge

class AnthropicProvider(BaseProvider):
    def __init__(self, config: Dict[str, Any], client: httpx.AsyncClient, config_manager=None):
        """Merge Anthropic-specific headers from config."""
        super().__init__(config, client, config_manager)
        for key, value in config.get("headers", {}).items():
            self.headers[key] = value

    async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        """Translate OpenAI-format request to Anthropic Messages API format."""
        # Anthropic API expects 'model', 'messages', 'max_tokens' at top level
        # and uses 'system' for system prompts, not part of messages array
        anthropic_request = {
            "model": provider_model_name,
            "messages": request_body.get("messages", []),
            "max_tokens": request_body.get("max_tokens", 1024),
            "stream": request_body.get("stream", False)
        }
        
        for field in ["temperature", "system"]:
            if field in request_body:
                anthropic_request[field] = request_body[field]

        if options := model_config.get("options"):
            anthropic_request = deep_merge(anthropic_request, options)

        if anthropic_request["stream"]:
            return self._stream_request(self.client, "/messages", anthropic_request)

        anthropic_timeout = self._get_timeout("anthropic_timeout", 600)

        response_json = await self._make_request(
            method="POST",
            path="/messages",
            request_body=anthropic_request,
            timeout=anthropic_timeout,
            request_id=request_body.get("request_id", "unknown")
        )
        
        return JSONResponse(content=response_json)
