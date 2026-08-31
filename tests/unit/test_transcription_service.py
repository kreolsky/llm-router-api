"""Unit tests for src/services/transcription_service.py."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.context import AuthContext, RequestContext
from src.core.usage_db import RequestStats
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


class TestSharedFunnel:

    @pytest.mark.asyncio
    async def test_create_transcription_rides_the_shared_resolver(self):
        """create_transcription dispatches through BaseService._resolve_target
        (the one funnel), not through its own copy of the preamble — so a
        cross-cutting policy added to the resolver reaches transcription too."""
        models = {"stt/model": {"provider": "stt"}}
        providers = {"stt": {"type": "openai", "base_url": "https://api.example.com"}}
        service = TranscriptionService(_make_config_manager(models, providers), model_service=MagicMock())

        provider_instance = SimpleNamespace(identity="passthrough")
        provider_instance.transcriptions = AsyncMock(return_value={"text": "ok"})

        with patch("src.services.base.get_provider_instance",
                   new=AsyncMock(return_value=provider_instance)), \
             patch.object(
                 TranscriptionService, "_resolve_target",
                 new=AsyncMock(return_value=SimpleNamespace(
                     request_id="req-stt", user_id="proj",
                     stats=RequestStats(model_id="stt/model", provider_name="stt"),
                     error_ctx={"request_id": "req-stt", "user_id": "proj", "model_id": "stt/model"},
                     model_config=models["stt/model"], provider_name="stt",
                     provider_model_name="stt/model", provider_config=providers["stt"],
                     provider=provider_instance,
                     identity_headers={"user-agent": "oc/1.0"},
                 )),
             ) as mock_resolve:
            response = await service.create_transcription(
                _make_request(), _make_audio_file(), _make_auth_context(), model_id="stt/model"
            )

        assert response == {"text": "ok"}
        mock_resolve.assert_awaited_once()
        # identity headers come from the resolver, not from a local rebuild
        kwargs = provider_instance.transcriptions.call_args.kwargs
        assert kwargs["extra_headers"] == {"user-agent": "oc/1.0"}

    @pytest.mark.asyncio
    async def test_no_reasoning_effort_policy_applied_to_transcription(self):
        """Even a model carrying a reasoning_effort block must not have it
        injected on the transcription path — the policy lives in the JSON
        wrapper, not in the shared resolver."""
        models = {"stt/model": {
            "provider": "stt",
            "reasoning_effort": {"allowed": ["low", "high"], "default": "high"},
        }}
        providers = {"stt": {"type": "openai", "base_url": "https://api.example.com"}}
        service = TranscriptionService(_make_config_manager(models, providers), model_service=MagicMock())

        provider_instance = SimpleNamespace(identity=None)
        provider_instance.transcriptions = AsyncMock(return_value={"text": "ok"})
        with patch("src.services.base.get_provider_instance",
                   new=AsyncMock(return_value=provider_instance)):
            await service.create_transcription(
                _make_request(), _make_audio_file(), _make_auth_context(), model_id="stt/model"
            )

        call = provider_instance.transcriptions.call_args
        body = call.args[0]
        assert set(body["params"].keys()) == {"language", "temperature", "response_format", "return_timestamps"}


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
        with patch("src.services.base.get_provider_instance",
                   new=AsyncMock(return_value=provider_instance)):
            response = await service.create_transcription(
                request, _make_audio_file(), _make_auth_context(), model_id="stt/model"
            )

        assert response == {"text": "ok"}
        kwargs = provider_instance.transcriptions.call_args.kwargs
        assert kwargs["extra_headers"] == {"user-agent": "Kilo-Code/7.5.5"}
