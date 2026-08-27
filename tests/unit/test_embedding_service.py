"""Unit tests for src/services/embedding_service.py."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock

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
