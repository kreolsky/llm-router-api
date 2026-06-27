"""Unit tests for src/services/base.py — BaseService class."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from src.services.base import BaseService
from src.core.context import RequestContext
from src.core.error_handling import ErrorType, create_error


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_auth_data(project_name="test-project", api_key="sk-123",
                    allowed_models=None, extra=None):
    """Return a 4-tuple matching auth_data convention."""
    return (project_name, api_key, allowed_models or [], extra or [])


def _make_config_manager(models=None, providers=None):
    """Return a mock ConfigManager with get_config wired up."""
    cm = MagicMock()
    config = {
        "models": models or {},
        "providers": providers or {},
    }
    cm.get_config.return_value = config
    return cm


def _make_request(request_id="req-abc", project_name=None):
    """Return a mock FastAPI Request with a typed RequestContext."""
    request = MagicMock()
    request.state = SimpleNamespace(
        request_context=RequestContext(request_id=request_id, project_name=project_name)
    )
    return request


def _build_service(models=None, providers=None):
    cm = _make_config_manager(models, providers)
    return BaseService(cm)


# ===================================================================
# _get_request_context
# ===================================================================

class TestGetRequestContext:

    def test_with_request_id(self):
        """Request with request_id returns it in context."""
        svc = _build_service()
        request = _make_request("req-42", project_name="my-project")
        ctx = svc._get_request_context(request)
        assert ctx["request_id"] == "req-42"
        assert ctx["user_id"] == "my-project"

    def test_without_request_returns_unknown(self):
        """Without request, request_id is 'unknown'."""
        svc = _build_service()
        ctx = svc._get_request_context(None)
        assert ctx["request_id"] == "unknown"
        assert ctx["user_id"] == "unknown"

    def test_extracts_user_id_from_project_name(self):
        """user_id matches the project_name from the typed context."""
        svc = _build_service()
        request = _make_request("req-1", project_name="acme-corp")
        ctx = svc._get_request_context(request)
        assert ctx["user_id"] == "acme-corp"

    def test_user_id_unknown_when_project_name_none(self):
        """user_id is 'unknown' when project_name is not yet set."""
        svc = _build_service()
        request = _make_request("req-1", project_name=None)
        ctx = svc._get_request_context(request)
        assert ctx["user_id"] == "unknown"


# ===================================================================
# _validate_and_get_config
# ===================================================================

class TestValidateAndGetConfig:

    def test_empty_model_raises_400(self):
        """Empty model string raises handle_model_not_specified (400)."""
        svc = _build_service()
        auth_data = _make_auth_data()
        with pytest.raises(HTTPException) as exc_info:
            svc._validate_and_get_config("", auth_data, model_id="")
        assert exc_info.value.status_code == 400

    def test_none_model_raises_400(self):
        """None model raises handle_model_not_specified (400)."""
        svc = _build_service()
        auth_data = _make_auth_data()
        with pytest.raises(HTTPException) as exc_info:
            svc._validate_and_get_config(None, auth_data, model_id=None)
        assert exc_info.value.status_code == 400

    def test_model_not_in_allowed_raises_403(self):
        """Model not in allowed_models raises handle_model_not_allowed (403)."""
        svc = _build_service(
            models={"gpt-4": {"provider": "openai"}},
            providers={"openai": {"type": "openai", "base_url": "https://api.openai.com"}}
        )
        auth_data = _make_auth_data(allowed_models=["gpt-3.5-turbo"])
        with pytest.raises(HTTPException) as exc_info:
            svc._validate_and_get_config("gpt-4", auth_data, model_id="gpt-4")
        assert exc_info.value.status_code == 403

    def test_model_not_in_config_raises_404(self):
        """Model not in config raises handle_model_not_found (404)."""
        svc = _build_service(models={})
        auth_data = _make_auth_data()  # empty allowed_models = unrestricted
        with pytest.raises(HTTPException) as exc_info:
            svc._validate_and_get_config("nonexistent-model", auth_data, model_id="nonexistent-model")
        assert exc_info.value.status_code == 404

    def test_provider_not_in_config_raises_404(self):
        """Provider not in config raises handle_provider_not_found (404)."""
        svc = _build_service(
            models={"gpt-4": {"provider": "missing-provider"}},
            providers={}
        )
        auth_data = _make_auth_data()
        with pytest.raises(HTTPException) as exc_info:
            svc._validate_and_get_config("gpt-4", auth_data, model_id="gpt-4")
        assert exc_info.value.status_code == 404

    def test_happy_path_returns_tuple(self):
        """Happy path returns (model_config, provider_name, provider_model_name, provider_config)."""
        models = {
            "my-model": {
                "provider": "openai",
                "provider_model_name": "gpt-4-turbo",
                "options": {"temperature": 0.7}
            }
        }
        providers = {
            "openai": {"type": "openai", "base_url": "https://api.openai.com"}
        }
        svc = _build_service(models=models, providers=providers)
        auth_data = _make_auth_data()

        model_config, provider_name, provider_model_name, provider_config = \
            svc._validate_and_get_config("my-model", auth_data, model_id="my-model")

        assert model_config == models["my-model"]
        assert provider_name == "openai"
        assert provider_model_name == "gpt-4-turbo"
        assert provider_config == providers["openai"]

    def test_happy_path_defaults_provider_model_name(self):
        """When provider_model_name is absent, defaults to the requested model name."""
        models = {"gpt-4": {"provider": "openai"}}
        providers = {"openai": {"type": "openai"}}
        svc = _build_service(models=models, providers=providers)
        auth_data = _make_auth_data()

        _, _, provider_model_name, _ = svc._validate_and_get_config("gpt-4", auth_data, model_id="gpt-4")
        assert provider_model_name == "gpt-4"

    def test_empty_allowed_models_unrestricted(self):
        """Empty allowed_models list means unrestricted access -- no 403."""
        models = {"gpt-4": {"provider": "openai"}}
        providers = {"openai": {"type": "openai"}}
        svc = _build_service(models=models, providers=providers)
        auth_data = _make_auth_data(allowed_models=[])

        model_config, *_ = svc._validate_and_get_config("gpt-4", auth_data, model_id="gpt-4")
        assert model_config is not None

    def test_model_in_allowed_models_succeeds(self):
        """When allowed_models is non-empty and requested model IS in the list, validation passes."""
        models = {"gpt-4": {"provider": "openai", "provider_model_name": "gpt-4-turbo"}}
        providers = {"openai": {"type": "openai", "base_url": "https://api.openai.com"}}
        svc = _build_service(models=models, providers=providers)
        auth_data = _make_auth_data(allowed_models=["gpt-4"])

        model_config, provider_name, provider_model_name, provider_config = \
            svc._validate_and_get_config("gpt-4", auth_data, model_id="gpt-4")

        assert model_config == models["gpt-4"]
        assert provider_name == "openai"
        assert provider_model_name == "gpt-4-turbo"

    def test_invariant_access_check_before_existence(self):
        """INVARIANT: access check runs before existence check.

        A model that is NOT in allowed_models AND NOT in config should
        produce 403 (not 404), preventing information leakage.
        """
        svc = _build_service(models={})  # model does not exist in config
        auth_data = _make_auth_data(allowed_models=["only-this-model"])

        with pytest.raises(HTTPException) as exc_info:
            svc._validate_and_get_config("secret-model", auth_data, model_id="secret-model")
        # Must be 403 (access denied), not 404 (not found)
        assert exc_info.value.status_code == 403


# ===================================================================
# _get_provider
# ===================================================================

class TestGetProvider:

    @patch("src.services.base.get_provider_instance")
    def test_valid_config_returns_provider(self, mock_get):
        """Valid config returns a provider instance."""
        mock_provider = MagicMock()
        mock_get.return_value = mock_provider

        svc = _build_service()
        provider_config = {"type": "openai", "base_url": "https://api.openai.com"}

        result = svc._get_provider("openai", provider_config)
        assert result is mock_provider
        mock_get.assert_called_once_with(
            "openai", provider_config, svc.config_manager
        )

    @patch("src.services.base.get_provider_instance")
    def test_invalid_type_raises(self, mock_get):
        """Invalid provider type raises (factory raises HTTPException via create_error)."""
        mock_get.side_effect = HTTPException(status_code=404, detail="not found")

        svc = _build_service()
        provider_config = {"type": "bad"}

        with pytest.raises(HTTPException) as exc_info:
            svc._get_provider("bad", provider_config)
        assert exc_info.value.status_code == 404
