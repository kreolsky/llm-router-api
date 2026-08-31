"""OpenAI-compatible provider for chat, embeddings, and transcription."""
from collections.abc import AsyncGenerator
from typing import Any

from .base import BaseProvider


class OpenAICompatibleProvider(BaseProvider):
    async def chat_completions(self, request_body: dict[str, Any], provider_model_name: str,
                               model_config: dict[str, Any], request_id: str = "unknown",
                               extra_headers: dict[str, str] = None) -> dict[str, Any]:
        """Forward a non-streaming chat completion to an OpenAI-compatible API."""
        request_body = self._apply_model_config(request_body, provider_model_name, model_config)

        connect_timeout = self.settings.openai_connect_timeout
        # WHY: read is capped by stream_read_timeout — the same env knob aclose()
        # drains on as "the longest a legitimate request may run" — so a silent
        # upstream cannot hold the concurrency slot and _inflight forever.
        read_timeout = self.settings.stream_read_timeout
        non_stream_timeout = self._create_timeout(connect=connect_timeout, read=read_timeout)

        return await self._make_request(
            method="POST",
            path="/chat/completions",
            request_body=request_body,
            extra_headers=extra_headers,
            timeout=non_stream_timeout,
            request_id=request_id
        )

    def chat_completions_stream(self, request_body: dict[str, Any], provider_model_name: str,
                                model_config: dict[str, Any], request_id: str = "unknown",
                                extra_headers: dict[str, str] = None) -> AsyncGenerator[bytes, None]:
        """Forward a streaming chat completion to an OpenAI-compatible API."""
        request_body = self._apply_model_config(request_body, provider_model_name, model_config)
        return self._stream_request(self.pool.client, "/chat/completions", request_body,
                                    request_id=request_id, extra_headers=extra_headers)

    async def transcriptions(self, request_body: dict[str, Any], provider_model_name: str,
                             model_config: dict[str, Any], request_id: str = "unknown",
                             extra_headers: dict[str, str] = None) -> dict[str, Any]:
        """Send audio to an OpenAI-compatible /audio/transcriptions endpoint.

        Uses provider's own credentials from self.headers (set in BaseProvider.__init__).
        extra_headers (client identity) ride along; the multipart Content-Type
        is still set by httpx — _make_request pops it for multipart bodies.
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

        # WHY raw bytes, not io.BytesIO: the 429 retry loop lives below this
        # construction site (in _make_request_inner), so the
        # files tuple is encoded once per attempt. httpx's multipart encoder
        # happens to seek(0) seekable file objects today, but bytes make each
        # attempt self-contained by construction instead of by accommodation —
        # the provider layer must not depend on upload rewinding.
        files = {"file": (audio["filename"], audio["data"], audio["content_type"])}

        transcription_read_timeout = self.settings.openai_transcription_timeout
        transcription_timeout = self._create_timeout(read=transcription_read_timeout)

        return await self._make_request(
            method="POST",
            path="/audio/transcriptions",
            files=files,
            data=form,
            extra_headers=extra_headers,
            timeout=transcription_timeout,
            request_id=request_id
        )

    async def embeddings(self, request_body: dict[str, Any], provider_model_name: str,
                         model_config: dict[str, Any], request_id: str = "unknown",
                         extra_headers: dict[str, str] = None) -> Any:
        """Forward embedding request to an OpenAI-compatible API."""
        request_body = self._apply_model_config(request_body, provider_model_name, model_config)

        read_timeout = self.settings.openai_embeddings_read_timeout
        # WHY: no hardcoded connect/write/pool — the client's own defaults
        # (HTTPX_CONNECT_TIMEOUT etc.) cover them via _create_timeout fallback.
        embeddings_timeout = self._create_timeout(read=read_timeout)

        return await self._make_request(
            method="POST",
            path="/embeddings",
            request_body=request_body,
            extra_headers=extra_headers,
            timeout=embeddings_timeout,
            request_id=request_id
        )

    async def list_models(self, request_id: str = "unknown") -> dict[str, Any]:
        """Return the provider's /models list."""
        return await self._make_request(
            method="GET",
            path="/models",
            request_id=request_id
        )
