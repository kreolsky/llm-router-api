import httpx
import json
from typing import Dict, Any
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi import HTTPException, status

from .base import BaseProvider
from ..utils.deep_merge import deep_merge

class OllamaProvider(BaseProvider):
    def __init__(self, config: Dict[str, Any], client: httpx.AsyncClient):
        super().__init__(config, client)
        self.headers["Content-Type"] = "application/json"

    async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        ollama_request_body = {
            "model": provider_model_name,
            "messages": request_body.get("messages", []),
            "stream": request_body.get("stream", False)
        }

        # Map OpenAI-like parameters to Ollama's 'options'
        ollama_options = {}
        if "temperature" in request_body:
            ollama_options["temperature"] = request_body["temperature"]
        if "top_p" in request_body:
            ollama_options["top_p"] = request_body["top_p"]
        if "max_tokens" in request_body:
            ollama_options["num_predict"] = request_body["max_tokens"]
        if "stop" in request_body:
            ollama_options["stop"] = request_body["stop"]
        if "presence_penalty" in request_body:
            ollama_options["presence_penalty"] = request_body["presence_penalty"]
        if "frequency_penalty" in request_body:
            ollama_options["frequency_penalty"] = request_body["frequency_penalty"]
        
        if ollama_options:
            ollama_request_body["options"] = ollama_options

        try:
            if ollama_request_body["stream"]:
                return await self._stream_request(self.client, "/chat", ollama_request_body)
            else:
                response = await self.client.post(f"{self.base_url}/chat",
                                             headers=self.headers,
                                             json=ollama_request_body,
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

    async def embeddings(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        # Ollama embeddings API expects 'model' and 'prompt'
        # The incoming request_body is OpenAI-compatible, with 'input'
        ollama_request_body = {
            "model": provider_model_name,
            "prompt": request_body.get("input") # Map OpenAI 'input' to Ollama 'prompt'
        }

        try:
            response = await self.client.post(f"{self.base_url}/embeddings",
                                             headers=self.headers,
                                             json=ollama_request_body,
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

    async def transcriptions(self, audio_file: Any, request_params: Dict[str, Any], model_config: Dict[str, Any]) -> Any:
        raise NotImplementedError("OllamaProvider does not support transcriptions.")