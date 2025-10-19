import httpx
from typing import Dict, Any
from fastapi import HTTPException, status
import io

from .base import BaseProvider
from ..utils.deep_merge import deep_merge
from ..core.logging import logger
from ..core.error_handling import ErrorHandler, ErrorContext

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

        # DEBUG логирование запроса к провайдеру
        logger.debug_data(
            title="OpenAI Request",
            data={
                "url": f"{self.base_url}/chat/completions",
                "headers": self.headers,
                "request_body": request_body,
                "provider_model_name": provider_model_name,
                "model_config": model_config
            },
            request_id=request_body.get("request_id", "unknown"),
            component="openai_provider",
            data_flow="to_provider"
        )

        try:
            if stream:
                return await self._stream_request(self.client, "/chat/completions", request_body)
            else:
                # Optimized timeout for non-streaming chat completions
                # - connect: 10s to establish connection
                # - read: 60s for full response (most responses are much faster)
                # - write: 10s to send request
                # - pool: 10s to get connection from pool
                non_stream_timeout = httpx.Timeout(
                    connect=10.0,
                    read=60.0,
                    write=10.0,
                    pool=10.0
                )
                response = await self.client.post(f"{self.base_url}/chat/completions",
                                             headers=self.headers,
                                             json=request_body,
                                             timeout=non_stream_timeout)
                response.raise_for_status()
                response_json = response.json()
                
                # DEBUG логирование ответа от провайдера
                logger.debug_data(
                    title="OpenAI Response",
                    data=response_json,
                    request_id=request_body.get("request_id", "unknown"),
                    component="openai_provider",
                    data_flow="from_provider"
                )
                
                return response_json
        except httpx.HTTPStatusError as e:
            # Create error context - we don't have request info here, so use minimal context
            context = ErrorContext(provider_name="openai")
            raise ErrorHandler.handle_provider_http_error(e, context, "openai")
        except httpx.RequestError as e:
            context = ErrorContext(provider_name="openai")
            raise ErrorHandler.handle_provider_network_error(e, context, "openai")

    def _prepare_transcription_headers(self, api_key: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"}

    def _prepare_transcription_files(self, audio_data: bytes, filename: str, content_type: str) -> Dict[str, Any]:
        return {"file": (filename, io.BytesIO(audio_data), content_type)}

    def _process_transcription_params(self, **kwargs) -> Dict[str, Any]:
        transcription_params = {}
        if 'language' in kwargs:
            transcription_params['language'] = kwargs['language']
        if 'temperature' in kwargs:
            transcription_params['temperature'] = kwargs['temperature']
        if 'prompt' in kwargs:
            transcription_params['prompt'] = kwargs['prompt']
        if 'response_format' in kwargs:
            transcription_params['response_format'] = kwargs['response_format']
        
        # Handle return_timestamps logic
        if 'return_timestamps' in kwargs and kwargs['return_timestamps']:
            transcription_params['response_format'] = 'verbose_json'
        elif 'return_timestamps' in kwargs and not kwargs['return_timestamps'] and 'response_format' not in kwargs:
            transcription_params['response_format'] = 'json'
        
        return transcription_params

    async def transcriptions(
        self,
        audio_data: bytes,
        filename: str,
        content_type: str,
        model_id: str,
        api_key: str,
        base_url: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Sends audio data for transcription to the OpenAI-compatible service.
        """
        headers = self._prepare_transcription_headers(api_key)
        files = self._prepare_transcription_files(audio_data, filename, content_type)
        transcription_params = self._process_transcription_params(**kwargs)
        
        data = {"model": model_id, **transcription_params}

        try:
            response = await self.client.post(
                f"{base_url}/audio/transcriptions",
                headers=headers,
                files=files,
                data=data,
                timeout=3600.0 # Increased timeout for potentially large audio files
            )
            response.raise_for_status()
            response_json = response.json()
            
            # DEBUG логирование ответа от провайдера
            logger.debug_data(
                title="OpenAI Transcription Response",
                data=response_json,
                request_id="transcription_unknown",
                component="openai_provider",
                data_flow="from_provider"
            )
            
            return response_json
        except httpx.HTTPStatusError as e:
            context = ErrorContext(provider_name="openai")
            raise ErrorHandler.handle_provider_http_error(e, context, "openai")
        except httpx.RequestError as e:
            context = ErrorContext(provider_name="openai")
            raise ErrorHandler.handle_provider_network_error(e, context, "openai")

    async def embeddings(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        # Transform request: Replace the model name with the provider's specific model name
        request_body["model"] = provider_model_name
        
        # Merge options from model_config into the request_body
        options = model_config.get("options")
        if options:
            request_body = deep_merge(request_body, options)

        try:
            # Optimized timeout for embeddings (usually faster than chat)
            embeddings_timeout = httpx.Timeout(
                connect=10.0,
                read=30.0,   # Embeddings are typically fast
                write=10.0,
                pool=10.0
            )
            response = await self.client.post(f"{self.base_url}/embeddings",
                                             headers=self.headers,
                                             json=request_body,
                                             timeout=embeddings_timeout)
            response.raise_for_status()
            response_json = response.json()
            
            # DEBUG логирование ответа от провайдера
            logger.debug_data(
                title="OpenAI Embeddings Response",
                data=response_json,
                request_id=request_body.get("request_id", "unknown"),
                component="openai_provider",
                data_flow="from_provider"
            )
            
            return response_json
        except httpx.HTTPStatusError as e:
            context = ErrorContext(provider_name="openai")
            raise ErrorHandler.handle_provider_http_error(e, context, "openai")
        except httpx.RequestError as e:
            context = ErrorContext(provider_name="openai")
            raise ErrorHandler.handle_provider_network_error(e, context, "openai")
