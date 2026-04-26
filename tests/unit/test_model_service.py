"""Unit tests for src/services/model_service.py — ModelService class."""

from unittest.mock import MagicMock, AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from src.services.model_service import ModelService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_auth_data(project_name="test-project", api_key="sk-123",
                    allowed_models=None, allowed_endpoints=None):
    """Return a 4-tuple matching auth_data convention."""
    return (project_name, api_key, allowed_models or [], allowed_endpoints or [])


def _make_config(models=None, providers=None):
    """Return a config dict suitable for ConfigManager.get_config()."""
    return {
        "models": models or {},
        "providers": providers or {},
    }


def _build_service(models=None, providers=None):
    """Build a ModelService with a mocked ConfigManager."""
    cm = MagicMock()
    cm.get_config.return_value = _make_config(models, providers)
    client = MagicMock(spec=httpx.AsyncClient)
    return ModelService(cm, client)


# Sample model configs used across tests
SAMPLE_MODELS = {
    "model-a": {"provider": "prov-a", "provider_model_name": "a-real"},
    "model-b": {"provider": "prov-b", "provider_model_name": "b-real"},
    "model-c": {"provider": "prov-c", "provider_model_name": "c-real"},
    "hidden-model": {"provider": "prov-a", "provider_model_name": "h-real", "is_hidden": True},
}

SAMPLE_PROVIDERS = {
    "prov-a": {"type": "openai", "base_url": "https://a.example.com"},
    "prov-b": {"type": "openai", "base_url": "https://b.example.com"},
    "prov-c": {"type": "openai", "base_url": "https://c.example.com"},
}


# ===================================================================
# list_models
# ===================================================================

class TestListModels:

    @pytest.mark.asyncio
    async def test_unrestricted_user_sees_all_visible(self):
        """Empty allowed_models → all non-hidden models returned."""
        svc = _build_service(models=SAMPLE_MODELS)
        auth_data = _make_auth_data(allowed_models=[])

        result = await svc.list_models(auth_data)

        ids = [m["id"] for m in result["data"]]
        assert sorted(ids) == ["model-a", "model-b", "model-c"]
        assert "hidden-model" not in ids

    @pytest.mark.asyncio
    async def test_restricted_user_sees_only_allowed(self):
        """Non-empty allowed_models → only those models returned."""
        svc = _build_service(models=SAMPLE_MODELS)
        auth_data = _make_auth_data(allowed_models=["model-a"])

        result = await svc.list_models(auth_data)

        ids = [m["id"] for m in result["data"]]
        assert ids == ["model-a"]

    @pytest.mark.asyncio
    async def test_restricted_user_multiple_allowed(self):
        """Partial overlap: only allowed models that exist in config are returned."""
        svc = _build_service(models=SAMPLE_MODELS)
        auth_data = _make_auth_data(allowed_models=["model-a", "model-c"])

        result = await svc.list_models(auth_data)

        ids = sorted(m["id"] for m in result["data"])
        assert ids == ["model-a", "model-c"]

    @pytest.mark.asyncio
    async def test_hidden_model_excluded_even_if_allowed(self):
        """Hidden model is excluded from list even when in allowed_models."""
        svc = _build_service(models=SAMPLE_MODELS)
        auth_data = _make_auth_data(allowed_models=["model-a", "hidden-model"])

        result = await svc.list_models(auth_data)

        ids = [m["id"] for m in result["data"]]
        assert "hidden-model" not in ids
        assert ids == ["model-a"]

    @pytest.mark.asyncio
    async def test_allowed_model_not_in_config(self):
        """allowed_models references a model not in config — no crash, empty result."""
        svc = _build_service(models=SAMPLE_MODELS)
        auth_data = _make_auth_data(allowed_models=["nonexistent-model"])

        result = await svc.list_models(auth_data)

        assert result["data"] == []

    @pytest.mark.asyncio
    async def test_all_models_hidden(self):
        """When every model is hidden, list is empty for unrestricted user."""
        models = {
            "h1": {"provider": "p", "is_hidden": True},
            "h2": {"provider": "p", "is_hidden": True},
        }
        svc = _build_service(models=models)
        auth_data = _make_auth_data(allowed_models=[])

        result = await svc.list_models(auth_data)

        assert result["data"] == []

    @pytest.mark.asyncio
    async def test_response_structure(self):
        """Response has OpenAI-compatible structure."""
        svc = _build_service(models=SAMPLE_MODELS)
        auth_data = _make_auth_data(allowed_models=[])

        result = await svc.list_models(auth_data)

        assert result["object"] == "list"
        assert isinstance(result["data"], list)
        for model in result["data"]:
            assert model["object"] == "model"
            assert "id" in model
            assert "created" in model
            assert "owned_by" in model

    @pytest.mark.asyncio
    async def test_empty_config(self):
        """No models in config → empty list."""
        svc = _build_service(models={})
        auth_data = _make_auth_data(allowed_models=[])

        result = await svc.list_models(auth_data)

        assert result["data"] == []


# ===================================================================
# retrieve_model
# ===================================================================

class TestRetrieveModel:

    @pytest.mark.asyncio
    async def test_unrestricted_user_retrieves_model(self):
        """Unrestricted user can retrieve any existing model."""
        svc = _build_service(models=SAMPLE_MODELS, providers=SAMPLE_PROVIDERS)
        svc._get_model_details_from_provider = AsyncMock(return_value={})
        auth_data = _make_auth_data(allowed_models=[])

        result = await svc.retrieve_model("model-a", auth_data)

        assert result["id"] == "model-a"
        assert result["provider"] == "prov-a"

    @pytest.mark.asyncio
    async def test_restricted_user_retrieves_allowed(self):
        """Restricted user can retrieve a model in their allowed_models."""
        svc = _build_service(models=SAMPLE_MODELS, providers=SAMPLE_PROVIDERS)
        svc._get_model_details_from_provider = AsyncMock(return_value={})
        auth_data = _make_auth_data(allowed_models=["model-a"])

        result = await svc.retrieve_model("model-a", auth_data)

        assert result["id"] == "model-a"

    @pytest.mark.asyncio
    async def test_restricted_user_denied_disallowed(self):
        """Restricted user gets 403 for a model not in allowed_models."""
        svc = _build_service(models=SAMPLE_MODELS, providers=SAMPLE_PROVIDERS)
        auth_data = _make_auth_data(allowed_models=["model-a"])

        with pytest.raises(HTTPException) as exc_info:
            await svc.retrieve_model("model-b", auth_data)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_access_check_before_existence(self):
        """INVARIANT: disallowed + nonexistent model → 403, not 404."""
        svc = _build_service(models={})
        auth_data = _make_auth_data(allowed_models=["model-a"])

        with pytest.raises(HTTPException) as exc_info:
            await svc.retrieve_model("secret-model", auth_data)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_unrestricted_user_nonexistent_model(self):
        """Unrestricted user gets 404 for nonexistent model."""
        svc = _build_service(models={})
        auth_data = _make_auth_data(allowed_models=[])

        with pytest.raises(HTTPException) as exc_info:
            await svc.retrieve_model("no-such-model", auth_data)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_missing_provider_raises_404(self):
        """Model exists but its provider is not in config → 404."""
        models = {"orphan": {"provider": "missing-prov", "provider_model_name": "x"}}
        svc = _build_service(models=models, providers={})
        auth_data = _make_auth_data(allowed_models=[])

        with pytest.raises(HTTPException) as exc_info:
            await svc.retrieve_model("orphan", auth_data)
        assert exc_info.value.status_code == 404
