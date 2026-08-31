"""Unit tests for src/services/transcription_service.py."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import AuthContext, RequestContext
from src.services.transcription_service import TranscriptionService


def _make_auth_context():
    """AuthContext matching what auth.get_api_key builds."""
    return AuthContext(allowed_models=[], allowed_endpoints=[])


def _make_config_manager(models=None, providers=None, default_stt_model="stt/dummy"):
    from src.core.config_manager import Settings
    cm = MagicMock()
    cm.get_config.return_value = {
        "models": models or {},
        "providers": providers or {},
    }
    cm.settings = Settings(default_stt_model=default_stt_model)
    return cm


def _make_request(request_id="req-stt", project_name="proj"):
    request = MagicMock()
    request.state = SimpleNamespace(
        request_context=RequestContext(request_id=request_id, project_name=project_name)
    )
    return request


def _make_audio_file(filename="audio.wav", content_type="audio/wav", data=b"RIFF...."):
    audio = MagicMock()
    audio.filename = filename
    audio.content_type = content_type
    audio.read = AsyncMock(return_value=data)
    return audio


class TestIdentityHeadersForwarded:

    @pytest.mark.asyncio
    async def test_client_user_agent_reaches_provider(self):
        """identity: passthrough — the client's User-Agent rides along to the
        transcriptions call (multipart body; Content-Type is still owned by
        httpx via _make_request), so endpoints of one provider share one
        fingerprint."""
        models = {"stt/model": {"provider": "stt"}}
        providers = {"stt": {"type": "openai", "base_url": "https://api.example.com"}}
        service = TranscriptionService(_make_config_manager(models, providers), model_service=MagicMock())

        request = _make_request()
        request.headers = {"user-agent": "Kilo-Code/7.5.5", "authorization": "Bearer nnp-v1-x"}

        provider_instance = SimpleNamespace(identity="passthrough")
        provider_instance.transcriptions = AsyncMock(return_value={"text": "ok"})
        with patch("src.services.transcription_service.get_provider_instance",
                   new=AsyncMock(return_value=provider_instance)):
            response = await service.create_transcription(
                request, _make_audio_file(), _make_auth_context(), model_id="stt/model"
            )

        assert response == {"text": "ok"}
        kwargs = provider_instance.transcriptions.call_args.kwargs
        assert kwargs["extra_headers"] == {"user-agent": "Kilo-Code/7.5.5"}
