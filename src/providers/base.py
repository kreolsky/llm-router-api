import httpx
import json
import os
import logging # Import logging
from typing import Dict, Any, AsyncGenerator
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi import HTTPException, status

from ..utils.deep_merge import deep_merge # Import deep_merge from utils
from ..logging.config import logger # Import logger from logging_config

# logger = logging.getLogger("nnp-llm-router") # Initialize logger

class BaseProvider:
    def __init__(self, config: Dict[str, Any], client: httpx.AsyncClient):
        self.base_url = config.get("base_url")
        self.api_key_env = config.get("api_key_env")
        self.headers = config.get("headers", {})
        self.api_key = os.environ.get(self.api_key_env)
        self.client = client # Store the httpx client

        if not self.base_url:
            raise ValueError("Provider base_url is not configured.")
        if not self.api_key:
            raise ValueError(f"API key for {self.api_key_env} is not set in environment variables.")

        self.headers["Authorization"] = f"Bearer {self.api_key}"

    async def _stream_request(self, client: httpx.AsyncClient, url_path: str, request_body: Dict[str, Any]) -> StreamingResponse:
        async def generate():
            async with client.stream("POST", f"{self.base_url}{url_path}", 
                                     headers=self.headers, 
                                     json=request_body,
                                     timeout=600) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    yield chunk
        return StreamingResponse(generate(), media_type="text/event-stream")

    async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        raise NotImplementedError
