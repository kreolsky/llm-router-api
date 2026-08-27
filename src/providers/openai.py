"""OpenAI-compatible provider for chat, embeddings, and transcription."""
from typing import Dict, Any, AsyncGenerator
import io

from .base import BaseProvider


class OpenAICompatibleProvider(BaseProvider):
    async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str,
                               model_config: Dict[str, Any], request_id: str = "unknown",
                               extra_headers: Dict[str, str] = None) -> Dict[str, Any]:
        """Forward a non-streaming chat completion to an OpenAI-compatible API."""
        request_body = self._apply_model_config(request_body, provider_model_name, model_config)

        connect_timeout = self._get_timeout("openai_connect_timeout", 60.0)
        non_stream_timeout = self._create_timeout(connect=connect_timeout)

        return await self._make_request(
            method="POST",
            path="/chat/completions",
            request_body=request_body,
            extra_headers=extra_headers,
            timeout=non_stream_timeout,
            request_id=request_id
        )

    def chat_completions_stream(self, request_body: Dict[str, Any], provider_model_name: str,
                                model_config: Dict[str, Any], request_id: str = "unknown",
                                extra_headers: Dict[str, str] = None) -> AsyncGenerator[bytes, None]:
        """Forward a streaming chat completion to an OpenAI-compatible API."""
        request_body = self._apply_model_config(request_body, provider_model_name, model_config)
        return self._stream_request(self.client, "/chat/completions", request_body,
                                    request_id=request_id, extra_headers=extra_headers)

    async def transcriptions(self, request_body: Dict[str, Any], provider_model_name: str,
                             model_config: Dict[str, Any], request_id: str = "unknown") -> Dict[str, Any]:
        """Send audio to an OpenAI-compatible /audio/transcriptions endpoint.

        Uses provider's own credentials from self.headers (set in BaseProvider.__init__).
        """
        audio = request_body["audio"]
        params = dict(request_body.get("params") or {})

        # WHY: return_timestamps is a non-standard convenience flag; OpenAI Whisper
        # exposes the same data via response_format=verbose_json
        return_timestamps = params.pop("return_timestamps", None)
        if return_timestamps:
            params["response_format"] = "verbose_json"
        params.setdefault("response_format", "json")

        # Drop None values so we don't send empty form fields
        form = {k: v for k, v in params.items() if v is not None}
        form = self._apply_model_config(form, provider_model_name, model_config)

        files = {"file": (audio["filename"], io.BytesIO(audio["data"]), audio["content_type"])}

        transcription_read_timeout = self._get_timeout("openai_transcription_timeout", 3600.0)
        transcription_timeout = self._create_timeout(read=transcription_read_timeout)

        return await self._make_request(
            method="POST",
            path="/audio/transcriptions",
            files=files,
            data=form,
            timeout=transcription_timeout,
            request_id=request_id
        )

    async def embeddings(self, request_body: Dict[str, Any], provider_model_name: str,
                         model_config: Dict[str, Any], request_id: str = "unknown") -> Any:
        """Forward embedding request to an OpenAI-compatible API."""
        request_body = self._apply_model_config(request_body, provider_model_name, model_config)

        read_timeout = self._get_timeout("openai_embeddings_read_timeout", 30.0)
        embeddings_timeout = self._create_timeout(connect=10.0, read=read_timeout, write=10.0, pool=10.0)

        return await self._make_request(
            method="POST",
            path="/embeddings",
            request_body=request_body,
            timeout=embeddings_timeout,
            request_id=request_id
        )

    async def list_models(self, request_id: str = "unknown") -> Dict[str, Any]:
        """Return the provider's /models list."""
        return await self._make_request(
            method="GET",
            path="/models",
            request_id=request_id
        )

    async def get_model(self, provider_model_name: str, request_id: str = "unknown") -> Dict[str, Any]:
        """Return a single model's metadata from the provider's /models list.

        Returns {} when the model is not present in the list. Provider errors
        propagate to the caller (ModelService treats them as non-fatal).
        """
        models_data = await self.list_models(request_id=request_id)
        for model in models_data.get("data", []):
            if model.get("id") == provider_model_name:
                return model
        return {}

