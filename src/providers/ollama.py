"""Ollama provider mapping OpenAI-format requests to Ollama's API."""
import httpx
from typing import Dict, Any

from .base import BaseProvider

class OllamaProvider(BaseProvider):
    def __init__(self, config: Dict[str, Any], client: httpx.AsyncClient, config_manager=None):
        super().__init__(config, client, config_manager)

    async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str,
                               model_config: Dict[str, Any], request_id: str = "unknown") -> Any:
        """Map OpenAI-format chat request to Ollama's /chat endpoint."""
        ollama_request_body = {
            "model": provider_model_name,
            "messages": request_body.get("messages", []),
            "stream": request_body.get("stream", False)
        }

        # Map OpenAI-like parameters to Ollama's 'options' structure
        param_mapping = {
            "temperature": "temperature",
            "top_p": "top_p",
            "max_tokens": "num_predict",
            "stop": "stop",
            "presence_penalty": "presence_penalty",
            "frequency_penalty": "frequency_penalty"
        }

        ollama_options = {
            ollama_key: request_body[openai_key]
            for openai_key, ollama_key in param_mapping.items()
            if openai_key in request_body
        }

        if ollama_options:
            ollama_request_body["options"] = ollama_options

        if ollama_request_body["stream"]:
            return self._stream_request(self.client, "/chat", ollama_request_body, request_id=request_id)

        connect_timeout = self._get_timeout("ollama_connect_timeout", 60.0)
        ollama_timeout = self._create_timeout(connect=connect_timeout)

        return await self._make_request(
            method="POST",
            path="/chat",
            request_body=ollama_request_body,
            timeout=ollama_timeout,
            request_id=request_id
        )

    async def embeddings(self, request_body: Dict[str, Any], provider_model_name: str,
                         model_config: Dict[str, Any], request_id: str = "unknown") -> Any:
        """Map OpenAI 'input' field to Ollama 'prompt' for /embeddings."""
        ollama_request_body = {
            "model": provider_model_name,
            "prompt": request_body.get("input")
        }

        embeddings_timeout = self._create_timeout(connect=15.0, read=60.0, write=10.0, pool=10.0)

        return await self._make_request(
            method="POST",
            path="/embeddings",
            request_body=ollama_request_body,
            timeout=embeddings_timeout,
            request_id=request_id
        )

    async def transcriptions(self, request_body: Dict[str, Any], provider_model_name: str,
                             model_config: Dict[str, Any], request_id: str = "unknown") -> Any:
        raise NotImplementedError("OllamaProvider does not support transcriptions")