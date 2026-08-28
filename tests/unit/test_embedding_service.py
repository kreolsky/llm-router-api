"""Unit tests for src/services/embedding_service.py."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.core.context import RequestContext
from src.services.embedding_service import EmbeddingService


def _make_config_manager(models=None, providers=None):
    cm = MagicMock()
    cm.get_config.return_value = {
        "models": models or {},
        "providers": providers or {},
    }
    return cm


def _make_request(body: bytes, request_id="req-emb", project_name="proj"):
    """Mock Request whose .json() behaves like Starlette's on the given body."""
    request = MagicMock()
    request.state = SimpleNamespace(
        request_context=RequestContext(request_id=request_id, project_name=project_name)
    )
    request.json = AsyncMock(side_effect=lambda: json.loads(body))
    return request


class TestInvalidJsonBody:

    @pytest.mark.asyncio
    async def test_malformed_json_raises_400(self):
        """A body that is not valid JSON yields a 400, not an unhandled error."""
        service = EmbeddingService(_make_config_manager())
        request = _make_request(b"{not json")

        with pytest.raises(HTTPException) as exc_info:
            await service.create_embeddings(request, ("proj", "sk-1", [], []))

        assert exc_info.value.status_code == 400
        assert "valid JSON body" in exc_info.value.detail["error"]["message"]

    @pytest.mark.asyncio
    async def test_invalid_utf8_body_raises_400_not_500(self):
        """Non-UTF-8 bytes raise UnicodeDecodeError (not JSONDecodeError) — still a 400."""
        request = _make_request(b"\xff\xfe")
        request.json = AsyncMock(
            side_effect=UnicodeDecodeError("utf-8", b"\xff\xfe", 0, 1, "invalid start byte")
        )
        service = EmbeddingService(_make_config_manager())

        with pytest.raises(HTTPException) as exc_info:
            await service.create_embeddings(request, ("proj", "sk-1", [], []))

        assert exc_info.value.status_code == 400
        assert "valid JSON body" in exc_info.value.detail["error"]["message"]


class TestIdentityHeadersForwarded:

    @pytest.mark.asyncio
    async def test_client_user_agent_reaches_provider(self):
        """identity: passthrough — the client's User-Agent rides along to the
        embeddings call, so endpoints of one provider share one fingerprint."""
        models = {"emb/model": {"provider": "embed"}}
        providers = {"embed": {"type": "openai", "base_url": "https://api.example.com"}}
        service = EmbeddingService(_make_config_manager(models, providers))

        request = _make_request(json.dumps({"model": "emb/model", "input": "hi"}).encode())
        request.headers = {"user-agent": "Kilo-Code/7.5.5", "authorization": "Bearer nnp-v1-x"}

        provider_instance = SimpleNamespace(identity="passthrough")
        provider_instance.embeddings = AsyncMock(return_value={"data": [], "usage": {}})
        service._get_provider = AsyncMock(return_value=provider_instance)

        await service.create_embeddings(request, ("proj", "sk-1", [], []))

        kwargs = provider_instance.embeddings.call_args.kwargs
        assert kwargs["extra_headers"] == {"user-agent": "Kilo-Code/7.5.5"}
