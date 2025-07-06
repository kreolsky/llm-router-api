import httpx
import json
from typing import Dict, Any
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi import HTTPException, status

from .base import BaseProvider
from ..utils.deep_merge import deep_merge # Assuming deep_merge is in src/utils

class AnthropicProvider(BaseProvider):
    def __init__(self, config: Dict[str, Any], client: httpx.AsyncClient):
        super().__init__(config, client)
        self.headers["Content-Type"] = "application/json"
        # Anthropic specific headers
        for key, value in config.get("headers", {}).items():
            self.headers[key] = value

    async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        # Anthropic API expects 'model' and 'messages' at the top level
        # and 'max_tokens' is required.
        # It also uses 'system' for system prompts, not part of messages array.
        
        # Basic transformation for now, more complex mapping might be needed
        # depending on how closely OpenAI API is mimicked.
        anthropic_request = {
            "model": provider_model_name,
            "messages": request_body.get("messages", []),
            "max_tokens": request_body.get("max_tokens", 1024), # Ensure max_tokens is present
            "stream": request_body.get("stream", False)
        }
        if "temperature" in anthropic_request:
            anthropic_request["temperature"] = request_body["temperature"]
        if "system" in request_body: # Assuming system message is passed as a top-level key
            anthropic_request["system"] = request_body["system"]

        # Merge options from model_config into the anthropic_request
        options = model_config.get("options")
        if options:
            anthropic_request = deep_merge(anthropic_request, options)

        try:
            if anthropic_request["stream"]:
                return await self._stream_request(self.client, "/messages", anthropic_request)
            else:
                response = await self.client.post(f"{self.base_url}/messages", 
                                             headers=self.headers, 
                                             json=anthropic_request,
                                             timeout=600)
                response.raise_for_status()
                return JSONResponse(content=response.json())
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail={"error": {"message": f"Provider error: {e.response.text}", "code": f"provider_http_error_{e.response.status_code}"}},
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": {"message": f"Network error communicating with provider: {e}", "code": "provider_network_error"}},
            )
