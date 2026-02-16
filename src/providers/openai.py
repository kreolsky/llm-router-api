import httpx
from typing import Dict, Any
from fastapi import HTTPException, status
import io

from .base import BaseProvider
from ..utils.deep_merge import deep_merge
from ..core.logging import logger
from ..core.error_handling import ErrorHandler, ErrorContext

class OpenAICompatibleProvider(BaseProvider):
    def __init__(self, config: Dict[str, Any], client: httpx.AsyncClient, config_manager=None):
        super().__init__(config, client, config_manager)
        self.headers["Content-Type"] = "application/json"

    async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        """
        Handle chat completions requests to OpenAI-compatible APIs.
        
        This method transforms the request to use the provider-specific model name,
        merges model configuration options, and delegates to the base provider's
        unified request methods for consistent error handling and logging.
        
        Args:
            request_body: OpenAI-compatible request body
            provider_model_name: The model name to use for this provider
            model_config: Provider-specific model configuration including options
        
        Returns:
            For streaming: StreamingResponse with SSE content
            For non-streaming: JSON response from the provider
        """
        # Transform request: Replace the model name with the provider's specific model name
        request_body["model"] = provider_model_name
        
        # Merge options from model_config into the request_body
        if options := model_config.get("options"):
            request_body = deep_merge(request_body, options)

        # Stream or non-streaming request
        if request_body.get("stream", False):
            return await self._stream_request(self.client, "/chat/completions", request_body)
        
        # Optimized timeout for non-streaming chat completions
        # - connect: use config_manager.openai_connect_timeout
        # - read: None (disable read timeout)
        # - write: None (disable write timeout)
        # - pool: use client's pool timeout
        connect_timeout = self._get_timeout("openai_connect_timeout", 60.0)
        non_stream_timeout = httpx.Timeout(
            connect=connect_timeout,
            read=None,    # Disable read timeout
            write=None,   # Disable write timeout
            pool=self.client.timeout.pool
        )
        
        # Use the base provider's unified request method
        return await self._make_request(
            method="POST",
            path="/chat/completions",
            request_body=request_body,
            timeout=non_stream_timeout,
            request_id=request_body.get("request_id", "unknown")
        )

    def _prepare_transcription_headers(self, api_key: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"}

    def _prepare_transcription_files(self, audio_data: bytes, filename: str, content_type: str) -> Dict[str, Any]:
        return {"file": (filename, io.BytesIO(audio_data), content_type)}

    def _process_transcription_params(self, **kwargs) -> Dict[str, Any]:
        """
        Process transcription parameters from kwargs.
        
        Args:
            **kwargs: Transcription parameters (language, temperature, prompt, response_format, etc.)
        
        Returns:
            Dictionary of processed transcription parameters
        """
        # Standard transcription parameters
        transcription_params = {
            key: kwargs[key]
            for key in ['language', 'temperature', 'prompt', 'response_format']
            if key in kwargs
        }
        
        # Handle return_timestamps logic
        if 'return_timestamps' in kwargs:
            if kwargs['return_timestamps']:
                transcription_params['response_format'] = 'verbose_json'
            elif 'response_format' not in kwargs:
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
        
        This method prepares the transcription request with proper headers, files,
        and parameters, then delegates to the base provider's unified request method
        for consistent error handling and logging.
        
        Args:
            audio_data: Raw audio data bytes
            filename: Name of the audio file
            content_type: MIME type of the audio file (e.g., "audio/wav")
            model_id: Model ID to use for transcription
            api_key: API key for authentication
            base_url: Base URL for the transcription service
            **kwargs: Additional transcription parameters (language, temperature, prompt, etc.)
        
        Returns:
            JSON response containing the transcription result
        """
        headers = self._prepare_transcription_headers(api_key)
        files = self._prepare_transcription_files(audio_data, filename, content_type)
        transcription_params = self._process_transcription_params(**kwargs)
        
        data = {"model": model_id, **transcription_params}

        # Use config_manager.openai_transcription_timeout if available
        transcription_timeout = self._get_timeout("openai_transcription_timeout", 3600.0)
        
        # Use the base provider's unified request method with custom base_url
        # Note: We need to temporarily override base_url for this request
        original_base_url = self.base_url
        self.base_url = base_url
        
        try:
            response = await self._make_request(
                method="POST",
                path="/audio/transcriptions",
                headers=headers,
                files=files,
                data=data,
                timeout=transcription_timeout,
                request_id="transcription_unknown"
            )
            return response
        finally:
            # Restore original base_url
            self.base_url = original_base_url

    async def embeddings(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        """
        Handle embeddings requests to OpenAI-compatible APIs.
        
        This method transforms the request to use the provider-specific model name,
        merges model configuration options, and delegates to the base provider's
        unified request method for consistent error handling and logging.
        
        Args:
            request_body: OpenAI-compatible request body with 'input' field
            provider_model_name: The model name to use for this provider
            model_config: Provider-specific model configuration including options
        
        Returns:
            JSON response containing embeddings
        """
        # Transform request: Replace the model name with the provider's specific model name
        request_body["model"] = provider_model_name
        
        # Merge options from model_config into the request_body
        if options := model_config.get("options"):
            request_body = deep_merge(request_body, options)

        # Optimized timeout for embeddings (usually faster than chat)
        # Use config_manager.openai_embeddings_read_timeout if available
        read_timeout = self._get_timeout("openai_embeddings_read_timeout", 30.0)
        embeddings_timeout = httpx.Timeout(
            connect=10.0,
            read=read_timeout,   # Embeddings are typically fast
            write=10.0,
            pool=10.0
        )
        
        # Use the base provider's unified request method
        return await self._make_request(
            method="POST",
            path="/embeddings",
            request_body=request_body,
            timeout=embeddings_timeout,
            request_id=request_body.get("request_id", "unknown")
        )
