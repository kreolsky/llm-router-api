import httpx
import os
import json # Import json for parsing error responses
from typing import Dict, Any, AsyncGenerator
from fastapi.responses import StreamingResponse, JSONResponse

from ..utils.deep_merge import deep_merge
from ..core.exceptions import ProviderAPIError, ProviderNetworkError, ProviderStreamError # Import custom exceptions

class BaseProvider:
    def __init__(self, config: Dict[str, Any], client: httpx.AsyncClient):
        self.base_url = config.get("base_url")
        self.api_key_env = config.get("api_key_env")
        self.headers = config.get("headers", {})
        self.api_key = os.environ.get(self.api_key_env) if self.api_key_env else None
        self.client = client # Store the httpx client

        if not self.base_url:
            raise ValueError("Provider base_url is not configured.")
        
        # Only set API key and Authorization header if api_key_env is provided
        if self.api_key_env:
            if not self.api_key:
                raise ValueError(f"API key for {self.api_key_env} is not set in environment variables.")
            self.headers["Authorization"] = f"Bearer {self.api_key}"

    async def _stream_request(self, client: httpx.AsyncClient, url_path: str, request_body: Dict[str, Any]) -> StreamingResponse:
        """Stream request with optimized timeouts for streaming"""
        # Optimized timeout for streaming:
        # - connect: 10s to establish connection
        # - read: 30s between chunks (if no chunk in 30s, timeout)
        # - write: 10s to send request
        # - pool: 10s to get connection from pool
        stream_timeout = httpx.Timeout(
            connect=10.0,
            read=30.0,    # Time between chunks, not total time
            write=10.0,
            pool=10.0
        )
        
        async def generate():
            async with client.stream("POST", f"{self.base_url}{url_path}",
                                     headers=self.headers,
                                     json=request_body,
                                     timeout=stream_timeout) as response:
              try:
                  response.raise_for_status()
              except httpx.HTTPStatusError as e:
                  # Attempt to parse error message from provider's response body
                  error_message = f"Provider API error: {e.response.status_code} - {e.response.text}"
                  error_code = "provider_api_error"
                  try:
                      error_json = e.response.json()
                      if "error" in error_json and "message" in error_json["error"]:
                          error_message = error_json["error"]["message"]
                          if "code" in error_json["error"]:
                              error_code = error_json["error"]["code"]
                      elif "message" in error_json:
                          error_message = error_json["message"]
                  except json.JSONDecodeError:
                      pass # If not JSON, use the default error_message
                  
                  raise ProviderStreamError(
                      message=error_message,
                      status_code=e.response.status_code,
                      error_code=error_code,
                      original_exception=e
                  ) from e
              except httpx.RequestError as e:
                  # Raise custom network error
                  raise ProviderNetworkError(
                      message=f"Network or connection error to provider: {e}",
                      original_exception=e
                  ) from e
              
              async for chunk in response.aiter_bytes():
                  yield chunk
        return StreamingResponse(generate(), media_type="text/event-stream")

    async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        raise NotImplementedError

    async def embeddings(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        raise NotImplementedError

    async def transcriptions(self, audio_file: Any, request_params: Dict[str, Any], model_config: Dict[str, Any]) -> Any:
        raise NotImplementedError
