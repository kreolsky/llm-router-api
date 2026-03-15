"""OpenAI-compatible provider for chat, embeddings, and transcription."""
import httpx
from typing import Dict, Any
from fastapi import HTTPException, status
import io

from .base import BaseProvider
from ..core.logging import logger
from ..core.error_handling import ErrorHandler, ErrorContext

class OpenAICompatibleProvider(BaseProvider):
    def __init__(self, config: Dict[str, Any], client: httpx.AsyncClient, config_manager=None):
        super().__init__(config, client, config_manager)

    async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        """Forward chat completion to an OpenAI-compatible API, streaming or non-streaming."""
        request_body = self._apply_model_config(request_body, provider_model_name, model_config)

        if request_body.get("stream", False):
            return await self._stream_request(self.client, "/chat/completions", request_body)
        
        connect_timeout = self._get_timeout("openai_connect_timeout", 60.0)
        non_stream_timeout = self._create_timeout(connect=connect_timeout)
        
        return await self._make_request(
            method="POST",
            path="/chat/completions",
            request_body=request_body,
            timeout=non_stream_timeout,
            request_id=request_body.get("request_id", "unknown")
        )

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
        headers = {"Authorization": f"Bearer {api_key}"}
        files = {"file": (filename, io.BytesIO(audio_data), content_type)}

        # Build transcription parameters
        transcription_params = {
            key: kwargs[key]
            for key in ['language', 'temperature', 'prompt', 'response_format']
            if key in kwargs
        }
        if 'return_timestamps' in kwargs:
            if kwargs['return_timestamps']:
                transcription_params['response_format'] = 'verbose_json'
            elif 'response_format' not in kwargs:
                transcription_params['response_format'] = 'json'

        data = {"model": model_id, **transcription_params}
        transcription_timeout = self._get_timeout("openai_transcription_timeout", 3600.0)

        return await self._make_request(
            method="POST",
            path="/audio/transcriptions",
            headers=headers,
            files=files,
            data=data,
            timeout=transcription_timeout,
            request_id="transcription_unknown",
            base_url=base_url
        )

    async def embeddings(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        """Forward embedding request to an OpenAI-compatible API."""
        request_body = self._apply_model_config(request_body, provider_model_name, model_config)

        read_timeout = self._get_timeout("openai_embeddings_read_timeout", 30.0)
        embeddings_timeout = self._create_timeout(connect=10.0, read=read_timeout, write=10.0, pool=10.0)
        
        return await self._make_request(
            method="POST",
            path="/embeddings",
            request_body=request_body,
            timeout=embeddings_timeout,
            request_id=request_body.get("request_id", "unknown")
        )
