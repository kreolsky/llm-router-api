"""Unit tests for src/services/base.py — BaseService class."""

import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
from fastapi import HTTPException

from src.core.identity_headers import compile_passthrough_spec
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
        assert ctx.request_id == "req-42"
        assert ctx.user_id == "my-project"

    def test_without_request_returns_unknown(self):
        """Without request, request_id is 'unknown'."""
        svc = _build_service()
        ctx = svc._get_request_context(None)
        assert ctx.request_id == "unknown"
        assert ctx.user_id == "unknown"

    def test_extracts_user_id_from_project_name(self):
        """user_id matches the project_name from the typed context."""
        svc = _build_service()
        request = _make_request("req-1", project_name="acme-corp")
        ctx = svc._get_request_context(request)
        assert ctx.user_id == "acme-corp"

    def test_user_id_unknown_when_project_name_none(self):
        """user_id is 'unknown' when project_name is not yet set."""
        svc = _build_service()
        request = _make_request("req-1", project_name=None)
        ctx = svc._get_request_context(request)
        assert ctx.user_id == "unknown"

    def test_returns_typed_context(self):
        """The accessor returns the dataclass, not a stringly-typed dict."""
        svc = _build_service()
        ctx = svc._get_request_context(_make_request("req-9", project_name="p"))
        assert isinstance(ctx, RequestContext)

    def test_request_without_middleware_context(self):
        """A request that never passed through the middleware degrades to 'unknown'."""
        svc = _build_service()
        request = MagicMock()
        request.state = SimpleNamespace()
        ctx = svc._get_request_context(request)
        assert ctx.request_id == "unknown"
        assert ctx.user_id == "unknown"


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

    @pytest.mark.asyncio
    @patch("src.services.base.get_provider_instance", new_callable=AsyncMock)
    async def test_valid_config_returns_provider(self, mock_get):
        """Valid config returns a provider instance."""
        mock_provider = MagicMock()
        mock_get.return_value = mock_provider

        svc = _build_service()
        provider_config = {"type": "openai", "base_url": "https://api.openai.com"}

        result = await svc._get_provider("openai", provider_config)
        assert result is mock_provider
        mock_get.assert_called_once_with(
            "openai", provider_config, svc.config_manager
        )

    @pytest.mark.asyncio
    @patch("src.services.base.get_provider_instance", new_callable=AsyncMock)
    async def test_invalid_type_raises(self, mock_get):
        """Invalid provider type raises (factory raises HTTPException via create_error)."""
        mock_get.side_effect = HTTPException(status_code=404, detail="not found")

        svc = _build_service()
        provider_config = {"type": "bad"}

        with pytest.raises(HTTPException) as exc_info:
            await svc._get_provider("bad", provider_config)
        assert exc_info.value.status_code == 404


# ===================================================================
# _build_identity_headers / _extract_passthrough_headers
# ===================================================================

SESSION_ID_RE = re.compile(r"^ses_[0-9A-Za-z]{26}$")


def _make_identity_request(headers=None, request_id="req-1", project_name="proj"):
    """Mock request with real dict headers and a typed RequestContext."""
    request = MagicMock()
    request.headers = dict(headers or {})
    request.state = SimpleNamespace(
        request_context=RequestContext(request_id=request_id, project_name=project_name)
    )
    return request


def _make_identity_provider(identity=None, provider_name="glm", passthrough_headers=None):
    return SimpleNamespace(
        identity=identity,
        provider_name=provider_name,
        passthrough_spec=compile_passthrough_spec(passthrough_headers),
    )


def _build_identity_service():
    cm = _make_config_manager()
    cm.opencode_session_ttl = 3600.0
    return BaseService(cm)


class TestConfigurablePassthroughWhitelist:
    """passthrough_headers on the provider replaces the default whitelist."""

    def test_provider_spec_widens_whitelist(self):
        svc = _build_identity_service()
        request = _make_identity_request({
            "user-agent": "Kilo-Code/7.5.5",
            "x-kilocode-mode": "code",
            "x-title": "Kilo Code",
        })
        provider = _make_identity_provider(
            "passthrough", passthrough_headers=["User-Agent", "x-kilocode-*"])
        result = svc._build_identity_headers(provider, request)
        assert result == {"User-Agent": "Kilo-Code/7.5.5", "x-kilocode-mode": "code"}

    def test_provider_spec_narrows_whitelist(self):
        svc = _build_identity_service()
        request = _make_identity_request({"user-agent": "Kilo-Code/7.5.5",
                                          "x-session-affinity": "ses_abc"})
        provider = _make_identity_provider("passthrough", passthrough_headers=["User-Agent"])
        assert svc._build_identity_headers(provider, request) == {"User-Agent": "Kilo-Code/7.5.5"}

    def test_provider_without_spec_attribute_uses_default(self):
        """Legacy/duck-typed provider objects keep the default whitelist."""
        svc = _build_identity_service()
        request = _make_identity_request({"user-agent": "Kilo-Code/7.5.5"})
        provider = SimpleNamespace(identity="passthrough", provider_name="glm")
        assert svc._build_identity_headers(provider, request) == {"User-Agent": "Kilo-Code/7.5.5"}

    def test_kilo_session_headers_survive_default_passthrough(self):
        """Kilo is an opencode fork: its ses_* headers pass through untouched."""
        svc = _build_identity_service()
        request = _make_identity_request({
            "user-agent": "Kilo-Code/7.5.5",
            "x-session-affinity": "ses_01ab",
            "x-session-id": "ses_01ab",
            "x-parent-session-id": "ses_00zz",
        })
        result = svc._build_identity_headers(_make_identity_provider("passthrough"), request)
        assert result == {
            "User-Agent": "Kilo-Code/7.5.5",
            "x-session-affinity": "ses_01ab",
            "X-Session-Id": "ses_01ab",
            "x-parent-session-id": "ses_00zz",
        }


class TestExtractPassthroughHeaders:

    def test_whitelisted_headers_forwarded_with_canonical_casing(self):
        svc = _build_identity_service()
        request = _make_identity_request({
            "user-agent": "oc/1.0",
            "x-session-id": "ses_abc",
            "x-session-affinity": "ses_abc",
            "x-parent-session-id": "ses_parent",
            "anthropic-beta": "interleaved-thinking-2025-05-14",
        })
        forwarded = svc._extract_passthrough_headers(request)
        assert forwarded == {
            "User-Agent": "oc/1.0",
            "X-Session-Id": "ses_abc",
            "x-session-affinity": "ses_abc",
            "x-parent-session-id": "ses_parent",
            "anthropic-beta": "interleaved-thinking-2025-05-14",
        }

    def test_x_stainless_prefix_forwarded(self):
        svc = _build_identity_service()
        request = _make_identity_request({
            "x-stainless-lang": "js", "x-stainless-retry-count": "2",
        })
        forwarded = svc._extract_passthrough_headers(request)
        assert forwarded == {"x-stainless-lang": "js", "x-stainless-retry-count": "2"}

    def test_non_whitelisted_headers_dropped(self):
        svc = _build_identity_service()
        request = _make_identity_request({
            "authorization": "Bearer nnp-v1-x",
            "x-nnp-project": "proj",
            "x-request-id": "r1",
            "http-referer": "https://nnp.space",
            "content-type": "application/json",
            "cookie": "a=b",
        })
        assert svc._extract_passthrough_headers(request) == {}

    def test_none_request_returns_empty(self):
        assert _build_identity_service()._extract_passthrough_headers(None) == {}


class TestBuildIdentityHeaders:

    def test_provider_without_identity_returns_none(self):
        svc = _build_identity_service()
        request = _make_identity_request({"user-agent": "oc/1.0"})
        assert svc._build_identity_headers(_make_identity_provider(None), request) is None
        assert svc._build_identity_headers(SimpleNamespace(), request) is None

    def test_passthrough_forwards_whitelist_verbatim(self):
        svc = _build_identity_service()
        request = _make_identity_request({"user-agent": "oc/1.0", "x-custom": "no"})
        result = svc._build_identity_headers(_make_identity_provider("passthrough"), request)
        assert result == {"User-Agent": "oc/1.0"}

    def test_passthrough_with_no_harness_headers_returns_none(self):
        svc = _build_identity_service()
        request = _make_identity_request({"x-custom": "no"})
        result = svc._build_identity_headers(_make_identity_provider("passthrough"), request)
        assert result is None

    def test_opencode_synthesizes_matching_session_headers(self):
        svc = _build_identity_service()
        request = _make_identity_request()
        result = svc._build_identity_headers(_make_identity_provider("opencode"), request)
        assert set(result) == {"x-session-affinity", "X-Session-Id"}
        assert result["x-session-affinity"] == result["X-Session-Id"]
        assert SESSION_ID_RE.fullmatch(result["X-Session-Id"])

    def test_opencode_session_stable_per_project(self):
        svc = _build_identity_service()
        provider = _make_identity_provider("opencode")
        first = svc._build_identity_headers(provider, _make_identity_request(project_name="a"))
        second = svc._build_identity_headers(provider, _make_identity_request(project_name="a"))
        other = svc._build_identity_headers(provider, _make_identity_request(project_name="b"))
        assert first == second
        assert first["X-Session-Id"] != other["X-Session-Id"]

    def test_opencode_real_client_headers_win_over_synthetic(self):
        svc = _build_identity_service()
        request = _make_identity_request({
            "user-agent": "real-harness/2.0", "x-session-id": "ses_real",
        })
        result = svc._build_identity_headers(_make_identity_provider("opencode"), request)
        assert result["User-Agent"] == "real-harness/2.0"
        assert result["X-Session-Id"] == "ses_real"
        # Synthetic affinity still present and synthetic session dropped
        assert SESSION_ID_RE.fullmatch(result["x-session-affinity"])

    def test_opencode_without_project_falls_back_to_none_key(self):
        """No project_name → key 'provider:None', still stable across requests."""
        svc = _build_identity_service()
        provider = _make_identity_provider("opencode")
        first = svc._build_identity_headers(provider, _make_identity_request(project_name=None))
        second = svc._build_identity_headers(provider, _make_identity_request(project_name=None))
        assert first["X-Session-Id"] == second["X-Session-Id"]
