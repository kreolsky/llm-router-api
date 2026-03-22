"""Unit tests for src/providers/base.py — BaseProvider and retry_on_rate_limit."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import httpx
import pytest
from fastapi import HTTPException

from src.providers.base import BaseProvider, retry_on_rate_limit
from src.core.error_handling import ErrorType, create_error


# ---------------------------------------------------------------------------
# Concrete subclass so we can instantiate the (otherwise abstract-ish) base
# ---------------------------------------------------------------------------

class TestProvider(BaseProvider):
    """Minimal concrete provider for testing."""

    async def chat_completions(self, request_body, provider_model_name, model_config):
        raise NotImplementedError

    async def embeddings(self, request_body, provider_model_name, model_config):
        raise NotImplementedError

    async def transcriptions(self, audio_file, request_params, model_config):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(base_url="https://api.example.com", api_key_env="TEST_API_KEY", **extra):
    cfg = {"base_url": base_url, "api_key_env": api_key_env, **extra}
    return cfg


def _build_provider(base_url="https://api.example.com", api_key_env="TEST_API_KEY",
                     env_vars=None, config_manager=None, headers=None):
    """Build a TestProvider with mocked env and client."""
    config = {"base_url": base_url}
    if api_key_env is not None:
        config["api_key_env"] = api_key_env
    if headers is not None:
        config["headers"] = headers

    env = {"TEST_API_KEY": "sk-test-123"}
    if env_vars is not None:
        env.update(env_vars)

    client = MagicMock(spec=httpx.AsyncClient)
    client.timeout = httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=10.0)

    with patch.dict("os.environ", env, clear=False):
        provider = TestProvider(config, client, config_manager=config_manager)
    return provider


# ===================================================================
# retry_on_rate_limit decorator
# ===================================================================

class TestRetryOnRateLimit:
    """Tests for the retry_on_rate_limit decorator."""

    @pytest.mark.asyncio
    async def test_successful_first_try_no_retries(self):
        """Successful call on first try -- no retries."""
        call_count = 0

        @retry_on_rate_limit(max_retries=3, base_delay=0.01, max_delay=0.1)
        async def fn():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await fn()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_429_retried_up_to_max_then_raised(self):
        """429 error retried up to max_retries, then re-raised."""
        call_count = 0
        exc = HTTPException(status_code=429, detail="rate limited")

        @retry_on_rate_limit(max_retries=2, base_delay=0.001, max_delay=0.01)
        async def fn():
            nonlocal call_count
            call_count += 1
            raise exc

        with pytest.raises(HTTPException) as exc_info:
            await fn()
        assert exc_info.value.status_code == 429
        # initial attempt + 2 retries = 3 calls
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_non_429_error_raised_immediately(self):
        """Non-429 error raised immediately (no retry)."""
        call_count = 0

        @retry_on_rate_limit(max_retries=3, base_delay=0.001, max_delay=0.01)
        async def fn():
            nonlocal call_count
            call_count += 1
            raise HTTPException(status_code=500, detail="server error")

        with pytest.raises(HTTPException) as exc_info:
            await fn()
        assert exc_info.value.status_code == 500
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_exponential_backoff_formula(self):
        """Backoff delay = min(base * 2^attempt, max)."""
        recorded_delays = []
        exc = HTTPException(status_code=429, detail="rate limited")
        call_count = 0

        original_sleep = asyncio.sleep

        async def mock_sleep(delay):
            recorded_delays.append(delay)

        @retry_on_rate_limit(max_retries=4, base_delay=1.0, max_delay=10.0)
        async def fn():
            nonlocal call_count
            call_count += 1
            raise exc

        with patch("src.providers.base.asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(HTTPException):
                await fn()

        # attempts 0..3 → delays: min(1*2^0,10)=1, min(1*2^1,10)=2, min(1*2^2,10)=4, min(1*2^3,10)=8
        assert recorded_delays == [1.0, 2.0, 4.0, 8.0]

    @pytest.mark.asyncio
    async def test_config_resolution_cm_used_when_closure_arg_is_none(self):
        """Config from self.config_manager is used when decorator args are None."""
        cm = MagicMock()
        cm.provider_max_retries = 1
        cm.provider_retry_base_delay = 0.001
        cm.provider_retry_max_delay = 0.01

        call_count = 0

        # Decorator args are None → config_manager values used
        @retry_on_rate_limit()
        async def fn(self_obj):
            nonlocal call_count
            call_count += 1
            raise HTTPException(status_code=429, detail="rate limited")

        obj = SimpleNamespace(config_manager=cm)

        with patch("src.providers.base.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(HTTPException):
                await fn(obj)

        # cm.provider_max_retries=1 → 1 initial + 1 retry = 2
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_config_resolution_defaults_when_no_cm(self):
        """Without config_manager and without closure args, use hardcoded defaults (3 retries)."""
        call_count = 0

        @retry_on_rate_limit()
        async def fn():
            nonlocal call_count
            call_count += 1
            raise HTTPException(status_code=429, detail="rate limited")

        with patch("src.providers.base.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(HTTPException):
                await fn()

        # default max_retries=3 → 1 initial + 3 retries = 4
        assert call_count == 4


# ===================================================================
# BaseProvider.__init__
# ===================================================================

class TestBaseProviderInit:

    def test_missing_base_url_raises(self):
        """Missing base_url raises HTTPException."""
        config = {"api_key_env": "TEST_API_KEY"}
        client = MagicMock(spec=httpx.AsyncClient)
        with patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False):
            with pytest.raises(HTTPException) as exc_info:
                TestProvider(config, client)
        assert exc_info.value.status_code == 500

    def test_missing_api_key_env_var_raises(self):
        """Missing API key env var raises HTTPException."""
        config = {"base_url": "https://api.example.com", "api_key_env": "MISSING_KEY"}
        client = MagicMock(spec=httpx.AsyncClient)
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(HTTPException) as exc_info:
                TestProvider(config, client)
        assert exc_info.value.status_code == 500

    def test_no_api_key_env_no_error(self):
        """No api_key_env in config means no Authorization header, no error."""
        config = {"base_url": "https://api.example.com"}
        client = MagicMock(spec=httpx.AsyncClient)
        provider = TestProvider(config, client)
        assert "Authorization" not in provider.headers
        assert provider.api_key is None

    def test_successful_init(self):
        """Successful init sets headers, provider_name, base_url."""
        provider = _build_provider()
        assert provider.base_url == "https://api.example.com"
        assert provider.headers["Authorization"] == "Bearer sk-test-123"
        assert provider.headers["Content-Type"] == "application/json"
        assert provider.provider_name == "test"


# ===================================================================
# _apply_model_config
# ===================================================================

class TestApplyModelConfig:

    def test_sets_model_name(self):
        """Sets model name in request body."""
        provider = _build_provider()
        body = {"messages": []}
        model_config = {}
        result = provider._apply_model_config(body, "gpt-4", model_config)
        assert result["model"] == "gpt-4"

    def test_merges_options(self):
        """Merges options via deep_merge when present."""
        provider = _build_provider()
        body = {"messages": [], "temperature": 0.5}
        model_config = {"options": {"temperature": 0.9, "top_p": 0.8}}
        result = provider._apply_model_config(body, "gpt-4", model_config)
        assert result["model"] == "gpt-4"
        # deep_merge: options override existing keys
        assert result["temperature"] == 0.9
        assert result["top_p"] == 0.8

    def test_no_options_no_merge(self):
        """No options in model_config means no merge, body unchanged except model."""
        provider = _build_provider()
        body = {"messages": [], "temperature": 0.5}
        model_config = {}
        result = provider._apply_model_config(body, "gpt-4", model_config)
        assert result == {"messages": [], "temperature": 0.5, "model": "gpt-4"}


# ===================================================================
# _get_timeout
# ===================================================================

class TestGetTimeout:

    def test_with_config_manager(self):
        """With config_manager having the attr, returns config value."""
        cm = MagicMock()
        cm.openai_connect_timeout = 42.0
        provider = _build_provider(config_manager=cm)
        assert provider._get_timeout("openai_connect_timeout", 10.0) == 42.0

    def test_without_config_manager(self):
        """Without config_manager, returns default_value."""
        provider = _build_provider(config_manager=None)
        assert provider._get_timeout("openai_connect_timeout", 10.0) == 10.0

    def test_config_manager_missing_attr(self):
        """config_manager exists but lacks the attribute, returns default."""
        cm = MagicMock(spec=[])  # empty spec, no attributes
        provider = _build_provider(config_manager=cm)
        assert provider._get_timeout("nonexistent_timeout", 99.0) == 99.0


# ===================================================================
# _raise_provider_http_error
# ===================================================================

class TestRaiseProviderHttpError:

    def _make_http_status_error(self, status_code, json_body=None, text_body="error text"):
        """Helper to build a mock httpx.HTTPStatusError."""
        response = MagicMock(spec=httpx.Response)
        response.status_code = status_code
        response.text = text_body
        if json_body is not None:
            response.json.return_value = json_body
        else:
            response.json.side_effect = json.JSONDecodeError("", "", 0)
        request = MagicMock(spec=httpx.Request)
        error = httpx.HTTPStatusError("error", request=request, response=response)
        return error

    @patch("src.providers.base.log_provider_error")
    def test_extracts_nested_error_message(self, mock_log):
        """Extracts error message from JSON {"error": {"message": ...}}."""
        provider = _build_provider()
        err = self._make_http_status_error(
            400, json_body={"error": {"message": "bad request details"}}
        )
        with pytest.raises(HTTPException) as exc_info:
            provider._raise_provider_http_error(err, "req-1")
        assert exc_info.value.detail["error"]["message"] == "bad request details"
        assert exc_info.value.status_code == 400

    @patch("src.providers.base.log_provider_error")
    def test_extracts_flat_message(self, mock_log):
        """Extracts error message from {"message": ...}."""
        provider = _build_provider()
        err = self._make_http_status_error(
            422, json_body={"message": "validation failed"}
        )
        with pytest.raises(HTTPException) as exc_info:
            provider._raise_provider_http_error(err, "req-1")
        assert exc_info.value.detail["error"]["message"] == "validation failed"

    @patch("src.providers.base.log_provider_error")
    def test_falls_back_to_response_text(self, mock_log):
        """Falls back to response text when JSON parse fails."""
        provider = _build_provider()
        err = self._make_http_status_error(502, json_body=None, text_body="Bad Gateway")
        with pytest.raises(HTTPException) as exc_info:
            provider._raise_provider_http_error(err, "req-1")
        assert exc_info.value.detail["error"]["message"] == "Bad Gateway"

    @patch("src.providers.base.log_provider_error")
    def test_raises_with_correct_detail_structure(self, mock_log):
        """HTTPException detail has correct structure with code, message, metadata."""
        provider = _build_provider()
        err = self._make_http_status_error(
            503, json_body={"error": {"message": "overloaded"}}
        )
        with pytest.raises(HTTPException) as exc_info:
            provider._raise_provider_http_error(err, "req-1")
        detail = exc_info.value.detail
        assert detail["error"]["code"] == 503
        assert detail["error"]["metadata"]["provider_name"] == "test"
        assert "raw" in detail["error"]["metadata"]


# ===================================================================
# _create_timeout
# ===================================================================

class TestCreateTimeout:

    def test_returns_timeout_with_overrides(self):
        """Returns httpx.Timeout with specified overrides."""
        provider = _build_provider()
        timeout = provider._create_timeout(connect=1.0, read=2.0, write=3.0, pool=4.0)
        assert timeout.connect == 1.0
        assert timeout.read == 2.0
        assert timeout.write == 3.0
        assert timeout.pool == 4.0

    def test_inherits_connect_pool_from_client(self):
        """Inherits connect/pool from client when not specified."""
        provider = _build_provider()
        # Client timeout has connect=5.0, pool=10.0
        timeout = provider._create_timeout(read=99.0)
        assert timeout.connect == 5.0  # from client
        assert timeout.pool == 10.0    # from client
        assert timeout.read == 99.0
        assert timeout.write is None   # default when not specified
