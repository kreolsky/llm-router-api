"""Unit tests for src/services/base.py — BaseService class."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.core.context import AuthContext, RequestContext
from src.core.usage_db import RequestStats
from src.services.base import BaseService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_auth_context(project_name="test-project",
                       allowed_models=None, allowed_endpoints=None):
    """Return an AuthContext matching what auth.get_api_key builds."""
    return AuthContext(project_name, allowed_models or [], allowed_endpoints or [])


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
        auth_ctx = _make_auth_context()
        with pytest.raises(HTTPException) as exc_info:
            svc._validate_and_get_config("", auth_ctx, model_id="")
        assert exc_info.value.status_code == 400

    def test_none_model_raises_400(self):
        """None model raises handle_model_not_specified (400)."""
        svc = _build_service()
        auth_ctx = _make_auth_context()
        with pytest.raises(HTTPException) as exc_info:
            svc._validate_and_get_config(None, auth_ctx, model_id=None)
        assert exc_info.value.status_code == 400

    def test_model_not_in_allowed_raises_403(self):
        """Model not in allowed_models raises handle_model_not_allowed (403)."""
        svc = _build_service(
            models={"gpt-4": {"provider": "openai"}},
            providers={"openai": {"type": "openai", "base_url": "https://api.openai.com"}}
        )
        auth_ctx = _make_auth_context(allowed_models=["gpt-3.5-turbo"])
        with pytest.raises(HTTPException) as exc_info:
            svc._validate_and_get_config("gpt-4", auth_ctx, model_id="gpt-4")
        assert exc_info.value.status_code == 403

    def test_model_not_in_config_raises_404(self):
        """Model not in config raises handle_model_not_found (404)."""
        svc = _build_service(models={})
        auth_ctx = _make_auth_context()  # empty allowed_models = unrestricted
        with pytest.raises(HTTPException) as exc_info:
            svc._validate_and_get_config("nonexistent-model", auth_ctx, model_id="nonexistent-model")
        assert exc_info.value.status_code == 404

    def test_provider_not_in_config_raises_404(self):
        """Provider not in config raises handle_provider_not_found (404)."""
        svc = _build_service(
            models={"gpt-4": {"provider": "missing-provider"}},
            providers={}
        )
        auth_ctx = _make_auth_context()
        with pytest.raises(HTTPException) as exc_info:
            svc._validate_and_get_config("gpt-4", auth_ctx, model_id="gpt-4")
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
        auth_ctx = _make_auth_context()

        model_config, provider_name, provider_model_name, provider_config = \
            svc._validate_and_get_config("my-model", auth_ctx, model_id="my-model")

        assert model_config == models["my-model"]
        assert provider_name == "openai"
        assert provider_model_name == "gpt-4-turbo"
        assert provider_config == providers["openai"]

    def test_happy_path_defaults_provider_model_name(self):
        """When provider_model_name is absent, defaults to the requested model name."""
        models = {"gpt-4": {"provider": "openai"}}
        providers = {"openai": {"type": "openai"}}
        svc = _build_service(models=models, providers=providers)
        auth_ctx = _make_auth_context()

        _, _, provider_model_name, _ = svc._validate_and_get_config("gpt-4", auth_ctx, model_id="gpt-4")
        assert provider_model_name == "gpt-4"

    def test_empty_allowed_models_unrestricted(self):
        """Empty allowed_models list means unrestricted access -- no 403."""
        models = {"gpt-4": {"provider": "openai"}}
        providers = {"openai": {"type": "openai"}}
        svc = _build_service(models=models, providers=providers)
        auth_ctx = _make_auth_context(allowed_models=[])

        model_config, *_ = svc._validate_and_get_config("gpt-4", auth_ctx, model_id="gpt-4")
        assert model_config is not None

    def test_model_in_allowed_models_succeeds(self):
        """When allowed_models is non-empty and requested model IS in the list, validation passes."""
        models = {"gpt-4": {"provider": "openai", "provider_model_name": "gpt-4-turbo"}}
        providers = {"openai": {"type": "openai", "base_url": "https://api.openai.com"}}
        svc = _build_service(models=models, providers=providers)
        auth_ctx = _make_auth_context(allowed_models=["gpt-4"])

        model_config, provider_name, provider_model_name, provider_config = \
            svc._validate_and_get_config("gpt-4", auth_ctx, model_id="gpt-4")

        assert model_config == models["gpt-4"]
        assert provider_name == "openai"
        assert provider_model_name == "gpt-4-turbo"

    def test_invariant_access_check_before_existence(self):
        """INVARIANT: access check runs before existence check.

        A model that is NOT in allowed_models AND NOT in config should
        produce 403 (not 404), preventing information leakage.
        """
        svc = _build_service(models={})  # model does not exist in config
        auth_ctx = _make_auth_context(allowed_models=["only-this-model"])

        with pytest.raises(HTTPException) as exc_info:
            svc._validate_and_get_config("secret-model", auth_ctx, model_id="secret-model")
        # Must be 403 (access denied), not 404 (not found)
        assert exc_info.value.status_code == 403


# ===================================================================
# _prepare_dispatch — provider resolution
# ===================================================================

class TestPrepareDispatchProviders:
    """_prepare_dispatch resolves the provider via the registry directly.

    The old pass-through _get_provider wrapper is gone (inlined); these tests
    pin the resolution contract at its new call site.
    """

    @pytest.mark.asyncio
    @patch("src.services.base.get_provider_instance", new_callable=AsyncMock)
    async def test_resolves_provider_from_registry(self, mock_get):
        """A valid config yields the registry's instance on PreparedDispatch."""
        mock_provider = MagicMock()
        mock_get.return_value = mock_provider

        svc = _build_service(
            models={"gpt-4": {"provider": "openai"}},
            providers={"openai": {"type": "openai", "base_url": "https://api.example.com"}}
        )
        auth_ctx = _make_auth_context()
        request = _make_request("req-1")
        request.json = AsyncMock(return_value={"model": "gpt-4"})

        prepared = await svc._prepare_dispatch(
            request, auth_ctx, component="chat_service", log_title="Request JSON"
        )

        assert prepared.provider is mock_provider
        mock_get.assert_called_once_with("openai", svc.config_manager.get_config()["providers"]["openai"], svc.config_manager)

    @pytest.mark.asyncio
    @patch("src.services.base.get_provider_instance", new_callable=AsyncMock)
    async def test_registry_error_propagates(self, mock_get):
        """An invalid provider type raises (factory raises HTTPException via create_error)."""
        mock_get.side_effect = HTTPException(status_code=404, detail="not found")

        svc = _build_service(
            models={"gpt-4": {"provider": "bad"}},
            providers={"bad": {"type": "bad"}}
        )
        auth_ctx = _make_auth_context()
        request = _make_request("req-1")
        request.json = AsyncMock(return_value={"model": "gpt-4"})

        with pytest.raises(HTTPException) as exc_info:
            await svc._prepare_dispatch(
                request, auth_ctx, component="chat_service", log_title="Request JSON"
            )
        assert exc_info.value.status_code == 404


# ===================================================================
# _prepare_dispatch — preamble parity with the old duplicated lines
# ===================================================================

class TestPrepareDispatchPreamble:

    def _svc(self):
        return _build_service(
            models={"m": {"provider": "openai"}},
            providers={"openai": {"type": "openai", "base_url": "https://x.example.com"}}
        )

    def _request(self, body):
        request = _make_request("req-1", project_name="proj")
        request.json = AsyncMock(return_value=body)
        return request

    @pytest.mark.asyncio
    async def test_malformed_json_answers_400(self):
        svc = self._svc()
        request = self._request({})
        request.json = AsyncMock(side_effect=ValueError("bad utf-8"))
        with pytest.raises(HTTPException) as exc_info:
            await svc._prepare_dispatch(
                request, _make_auth_context(),
                component="c", log_title="t",
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    @patch("src.services.base.get_provider_instance", new_callable=AsyncMock)
    async def test_stats_enriched_and_identity_headers_built(self, mock_get):
        mock_get.return_value = SimpleNamespace(identity="passthrough")
        svc = self._svc()
        request = self._request({"model": "m"})
        request.headers = {"user-agent": "oc/1.0"}

        prepared = await svc._prepare_dispatch(
            request, _make_auth_context(), component="c", log_title="t"
        )

        assert prepared.requested_model == "m"
        assert prepared.stats.model_id == "m"
        assert prepared.stats.provider_name == "openai"
        assert prepared.identity_headers == {"user-agent": "oc/1.0"}
        assert prepared.error_ctx == {"request_id": "req-1", "user_id": "proj", "model_id": "m"}

    @pytest.mark.asyncio
    @patch("src.services.base.get_provider_instance", new_callable=AsyncMock)
    async def test_non_string_model_blanks_stats_model_id(self, mock_get):
        """A non-string "model" reaches the usage row as "", never as the raw value.

        The stats holder is enriched BEFORE validation rejects the request, so
        the blanking branch is observable on the real RequestStats even though
        the call raises. A truthy non-string (123) is used deliberately: None
        would short-circuit at MODEL_NOT_SPECIFIED without exercising it.
        """
        mock_get.return_value = SimpleNamespace(identity=None)
        svc = self._svc()
        request = self._request({"model": 123})
        request.headers = {}
        stats = RequestStats()
        request.state.request_stats = stats

        with pytest.raises(HTTPException) as exc_info:
            await svc._prepare_dispatch(
                request, _make_auth_context(), component="c", log_title="t"
            )
        assert exc_info.value.status_code == 404
        assert stats.model_id == ""


# ===================================================================
# _build_identity_headers / _extract_passthrough_headers
# ===================================================================

def _make_identity_request(headers=None, request_id="req-1", project_name="proj"):
    """Mock request with real dict headers and a typed RequestContext."""
    request = MagicMock()
    request.headers = dict(headers or {})
    request.state = SimpleNamespace(
        request_context=RequestContext(request_id=request_id, project_name=project_name)
    )
    return request


def _make_identity_provider(identity=None, provider_name="glm"):
    return SimpleNamespace(identity=identity, provider_name=provider_name)


def _build_identity_service():
    return BaseService(_make_config_manager())


class TestExtractPassthroughHeaders:
    """Full forward minus the denylist (core/header_policy.py)."""

    def test_client_headers_forwarded_verbatim(self):
        """Everything not denylisted goes up with the client's own spelling."""
        svc = _build_identity_service()
        request = _make_identity_request({
            "user-agent": "Kilo-Code/7.5.5",
            "x-session-id": "ses_01ab",
            "x-session-affinity": "ses_01ab",
            "x-kilocode-mode": "code",
            "anthropic-beta": "interleaved-thinking-2025-05-14",
            "accept": "application/json",
        })
        assert svc._extract_passthrough_headers(request) == {
            "user-agent": "Kilo-Code/7.5.5",
            "x-session-id": "ses_01ab",
            "x-session-affinity": "ses_01ab",
            "x-kilocode-mode": "code",
            "anthropic-beta": "interleaved-thinking-2025-05-14",
            "accept": "application/json",
        }

    def test_credential_headers_dropped(self):
        """Client credentials never reach the upstream — only the router's key goes."""
        svc = _build_identity_service()
        request = _make_identity_request({
            "authorization": "Bearer nnp-v1-x",
            "proxy-authorization": "Basic x",
            "cookie": "a=b",
            "x-api-key": "sk-client",
            "api-key": "sk-client",
            "x-goog-api-key": "sk-client",
            "user-agent": "oc/1.0",
        })
        assert svc._extract_passthrough_headers(request) == {"user-agent": "oc/1.0"}

    def test_transport_headers_dropped(self):
        """Hop-by-hop / framing values are stale: the router re-serializes the body."""
        svc = _build_identity_service()
        request = _make_identity_request({
            "host": "router:8777",
            "content-length": "123",
            "content-type": "application/json",
            "content-encoding": "gzip",
            "connection": "keep-alive",
            "transfer-encoding": "chunked",
            "te": "trailers",
            "upgrade": "h2c",
            "keep-alive": "timeout=5",
            "expect": "100-continue",
            "accept-encoding": "br, zstd",
        })
        assert svc._extract_passthrough_headers(request) == {}

    def test_topology_headers_dropped(self):
        """Reverse-proxy headers would leak internal IPs of the lab."""
        svc = _build_identity_service()
        request = _make_identity_request({
            "x-forwarded-for": "10.10.1.5",
            "x-forwarded-host": "internal.local",
            "x-real-ip": "10.10.1.5",
            "forwarded": "for=10.10.1.5",
            "true-client-ip": "10.10.1.5",
            "cf-connecting-ip": "10.10.1.5",
            "cdn-loop": "cdn1",
        })
        assert svc._extract_passthrough_headers(request) == {}

    def test_denylist_is_case_insensitive(self):
        svc = _build_identity_service()
        request = _make_identity_request({"X-Api-Key": "sk-client", "HOST": "router"})
        assert svc._extract_passthrough_headers(request) == {}

    def test_none_request_returns_empty(self):
        assert _build_identity_service()._extract_passthrough_headers(None) == {}


class TestBuildIdentityHeaders:

    def test_provider_without_identity_returns_none(self):
        svc = _build_identity_service()
        request = _make_identity_request({"user-agent": "oc/1.0"})
        assert svc._build_identity_headers(_make_identity_provider(None), request) is None
        assert svc._build_identity_headers(SimpleNamespace(), request) is None

    def test_passthrough_forwards_all_but_denylist(self):
        svc = _build_identity_service()
        request = _make_identity_request({
            "user-agent": "oc/1.0",
            "x-custom": "yes",
            "authorization": "Bearer nnp-v1-x",
        })
        result = svc._build_identity_headers(_make_identity_provider("passthrough"), request)
        assert result == {"user-agent": "oc/1.0", "x-custom": "yes"}

    def test_passthrough_with_only_denied_headers_returns_none(self):
        svc = _build_identity_service()
        request = _make_identity_request({"authorization": "Bearer nnp-v1-x"})
        result = svc._build_identity_headers(_make_identity_provider("passthrough"), request)
        assert result is None

    def test_none_request_returns_none_for_passthrough(self):
        svc = _build_identity_service()
        assert svc._build_identity_headers(_make_identity_provider("passthrough"), None) is None
