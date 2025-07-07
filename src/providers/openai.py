import httpx
from typing import Dict, Any
from fastapi import HTTPException, status
import io

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
            return response.json()
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail={"error": {"message": f"Transcription service error: {e.response.text}", "code": "transcription_service_error"}}
            ) from e
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error": {"message": f"Could not connect to transcription service: {e}", "code": "service_unavailable"}}
            ) from e

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
