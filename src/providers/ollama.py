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

        # DEBUG логирование запроса к провайдеру
        logger.debug_data(
            title="Ollama Request",
            data={
                "url": f"{self.base_url}/chat",
                "headers": self.headers,
                "request_body": ollama_request_body,
                "original_request_body": request_body,
                "provider_model_name": provider_model_name,
                "model_config": model_config
            },
            request_id=request_body.get("request_id", "unknown"),
            component="ollama_provider",
            data_flow="to_provider"
        )

        try:
            if ollama_request_body["stream"]:
                return await self._stream_request(self.client, "/chat", ollama_request_body)
            else:
                # Ollama can be slower than cloud providers (especially for large models)
                # Optimized timeout for non-streaming
                ollama_timeout = httpx.Timeout(
                    connect=15.0,  # Slightly longer for local/slow connections
                    read=120.0,    # 2 minutes for large model responses
                    write=10.0,
                    pool=10.0
                )
                response = await self.client.post(f"{self.base_url}/chat",
                                             headers=self.headers,
                                             json=ollama_request_body,
                                             timeout=ollama_timeout)
                response.raise_for_status()
                response_json = response.json()
                
                # DEBUG логирование ответа от провайдера
                logger.debug_data(
                    title="Ollama Response",
                    data=response_json,
                    request_id=request_body.get("request_id", "unknown"),
                    component="ollama_provider",
                    data_flow="from_provider"
                )
                
                return response_json
        except httpx.HTTPStatusError as e:
            context = ErrorContext(provider_name="ollama")
            raise ErrorHandler.handle_provider_http_error(e, context, "ollama")
        except httpx.RequestError as e:
            context = ErrorContext(provider_name="ollama")
            raise ErrorHandler.handle_provider_network_error(e, context, "ollama")

    async def embeddings(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        # Ollama embeddings API expects 'model' and 'prompt'
        # The incoming request_body is OpenAI-compatible, with 'input'
        ollama_request_body = {
            "model": provider_model_name,
            "prompt": request_body.get("input") # Map OpenAI 'input' to Ollama 'prompt'
        }

        # DEBUG логирование запроса к провайдеру
        logger.debug_data(
            title="Ollama Embedding Request",
            data={
                "url": f"{self.base_url}/embeddings",
                "headers": self.headers,
                "request_body": ollama_request_body,
                "original_request_body": request_body,
                "provider_model_name": provider_model_name,
                "model_config": model_config
            },
            request_id=request_body.get("request_id", "unknown"),
            component="ollama_provider",
            data_flow="to_provider"
        )

        try:
            # Ollama embeddings timeout
            embeddings_timeout = httpx.Timeout(
                connect=15.0,
                read=60.0,   # Embeddings can take time for large texts
                write=10.0,
                pool=10.0
            )
            response = await self.client.post(f"{self.base_url}/embeddings",
                                             headers=self.headers,
                                             json=ollama_request_body,
                                             timeout=embeddings_timeout)
            response.raise_for_status()
            response_json = response.json()
            
            # DEBUG логирование ответа от провайдера
            logger.debug_data(
                title="Ollama Embedding Response",
                data=response_json,
                request_id=request_body.get("request_id", "unknown"),
                component="ollama_provider",
                data_flow="from_provider"
            )
            
            return response_json
        except httpx.HTTPStatusError as e:
            context = ErrorContext(provider_name="ollama")
            raise ErrorHandler.handle_provider_http_error(e, context, "ollama")
        except httpx.RequestError as e:
            context = ErrorContext(provider_name="ollama")
            raise ErrorHandler.handle_provider_network_error(e, context, "ollama")

    async def transcriptions(self, audio_file: Any, request_params: Dict[str, Any], model_config: Dict[str, Any]) -> Any:
        context = ErrorContext(provider_name="ollama")
        raise ErrorHandler.handle_provider_config_error(
            error_details="OllamaProvider does not support transcriptions.",
            context=context
        )