import httpx
import json
from typing import Dict, Any
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi import HTTPException, status

from .base import BaseProvider
from ..utils.deep_merge import deep_merge
from ..core.error_handling import ErrorHandler, ErrorContext
from ..core.logging import logger

class OllamaProvider(BaseProvider):
    def __init__(self, config: Dict[str, Any], client: httpx.AsyncClient, config_manager=None):
        super().__init__(config, client, config_manager)

    async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        """
        Handle chat completions requests to Ollama API.
        
        This method transforms the OpenAI-compatible request to Ollama's format,
        mapping parameters to Ollama's 'options' structure. It delegates to the
        base provider's unified request methods for consistent error handling and logging.
        
        Args:
            request_body: OpenAI-compatible request body
            provider_model_name: The model name to use for this provider
            model_config: Provider-specific model configuration including options
        
        Returns:
            For streaming: StreamingResponse with SSE content
            For non-streaming: JSON response from Ollama
        """
        ollama_request_body = {
            "model": provider_model_name,
            "messages": request_body.get("messages", []),
            "stream": request_body.get("stream", False)
        }

        # Map OpenAI-like parameters to Ollama's 'options' using dictionary comprehension
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

        # Stream or non-streaming request
        if ollama_request_body["stream"]:
            return await self._stream_request(self.client, "/chat", ollama_request_body)
        
        connect_timeout = self._get_timeout("ollama_connect_timeout", 60.0)
        ollama_timeout = self._create_timeout(connect=connect_timeout)
        
        # Use the base provider's unified request method
        return await self._make_request(
            method="POST",
            path="/chat",
            request_body=ollama_request_body,
            timeout=ollama_timeout,
            request_id=request_body.get("request_id", "unknown")
        )

    async def embeddings(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        """
        Handle embeddings requests to Ollama API.
        
        This method transforms the OpenAI-compatible request to Ollama's format,
        mapping 'input' to 'prompt'. It delegates to the base provider's unified
        request method for consistent error handling and logging.
        
        Args:
            request_body: OpenAI-compatible request body with 'input' field
            provider_model_name: The model name to use for this provider
            model_config: Provider-specific model configuration including options
        
        Returns:
            JSON response containing embeddings from Ollama
        """
        # Ollama embeddings API expects 'model' and 'prompt'
        # The incoming request_body is OpenAI-compatible, with 'input'
        ollama_request_body = {
            "model": provider_model_name,
            "prompt": request_body.get("input") # Map OpenAI 'input' to Ollama 'prompt'
        }

        embeddings_timeout = self._create_timeout(connect=15.0, read=60.0, write=10.0, pool=10.0)
        
        # Use the base provider's unified request method
        return await self._make_request(
            method="POST",
            path="/embeddings",
            request_body=ollama_request_body,
            timeout=embeddings_timeout,
            request_id=request_body.get("request_id", "unknown")
        )

    async def transcriptions(self, audio_file: Any, request_params: Dict[str, Any], model_config: Dict[str, Any]) -> Any:
        context = ErrorContext(provider_name="ollama")
        raise ErrorHandler.handle_provider_config_error(
            error_details="OllamaProvider does not support transcriptions.",
            context=context
        )