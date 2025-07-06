import httpx
import json
from typing import Dict, Any
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi import HTTPException, status
from ..logging.config import logger # Import logger

from .base import BaseProvider
from ..utils.deep_merge import deep_merge # Assuming deep_merge is in src/utils

class OpenAICompatibleProvider(BaseProvider):
    def __init__(self, config: Dict[str, Any], client: httpx.AsyncClient):
        super().__init__(config, client)
        self.headers["Content-Type"] = "application/json"

    async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        # Transform request: Replace the model name with the provider's specific model name
        request_body["model"] = provider_model_name
        
        # Merge options from model_config into the request_body
        options = model_config.get("options")
        if options:
            request_body = deep_merge(request_body, options)

        # Ensure stream is handled correctly
        stream = request_body.get("stream", False)

        try:
            if stream:
                return await self._stream_request(self.client, "/chat/completions", request_body)
            else:
                response = await self.client.post(f"{self.base_url}/chat/completions", 
                                             headers=self.headers, 
                                             json=request_body,
                                             timeout=600) # Increased timeout for potentially long responses
                response.raise_for_status()
                return response.json()
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

    async def embeddings(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        # Transform request: Replace the model name with the provider's specific model name
        request_body["model"] = provider_model_name
        
        # Merge options from model_config into the request_body
        options = model_config.get("options")
        if options:
            request_body = deep_merge(request_body, options)

        try:
            response = await self.client.post(f"{self.base_url}/embeddings", 
                                             headers=self.headers, 
                                             json=request_body,
                                             timeout=600)
            response.raise_for_status()
            return response.json()
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
