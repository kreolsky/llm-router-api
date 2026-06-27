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

class ProviderStub(BaseProvider):
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
    """Build a ProviderStub with mocked env.

    The provider owns its own httpx.AsyncClient (built in __init__).
    """
    config = {"base_url": base_url}
    if api_key_env is not None:
        config["api_key_env"] = api_key_env
    if headers is not None:
        config["headers"] = headers

    env = {"TEST_API_KEY": "sk-test-123"}
    if env_vars is not None:
        env.update(env_vars)

    with patch.dict("os.environ", env, clear=False):
        provider = ProviderStub(config, config_manager=config_manager)
    return provider


def _make_cm(**overrides):
    """Build a SimpleNamespace config_manager with real values (no MagicMock magic)."""
    cm = SimpleNamespace()
    cm.queue_wait_timeout = overrides.get("queue_wait_timeout", 30.0)
    cm.provider_max_retries = overrides.get("provider_max_retries", 3)
    cm.provider_retry_base_delay = overrides.get("provider_retry_base_delay", 1.0)
    cm.provider_retry_max_delay = overrides.get("provider_retry_max_delay", 30.0)
    cm.httpx_max_connections = overrides.get("httpx_max_connections", 100)
    cm.httpx_max_keepalive_connections = overrides.get("httpx_max_keepalive_connections", 20)
    cm.httpx_connect_timeout = overrides.get("httpx_connect_timeout", 60.0)
    cm.httpx_read_timeout = overrides.get("httpx_read_timeout", 60.0)
    cm.httpx_pool_timeout = overrides.get("httpx_pool_timeout", 5.0)
    return cm


def _build_limited_provider(max_concurrent, config_manager=None):
    """Build a ProviderStub with max_concurrent set."""
    config = {"base_url": "https://api.example.com", "api_key_env": "TEST_API_KEY",
              "max_concurrent": max_concurrent}
    with patch.dict("os.environ", {"TEST_API_KEY": "sk-test-123"}, clear=False):
        return ProviderStub(config, config_manager=config_manager)


def _mock_response(json_body=None):
    """Build a mock httpx Response usable by _make_request_inner."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock(return_value=None)
    resp.json.return_value = json_body if json_body is not None else {"ok": True}
    resp.text = ""
    return resp


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
        with patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False):
            with pytest.raises(HTTPException) as exc_info:
                ProviderStub(config)
        assert exc_info.value.status_code == 500

    def test_missing_api_key_env_var_raises(self):
        """Missing API key env var raises HTTPException."""
        config = {"base_url": "https://api.example.com", "api_key_env": "MISSING_KEY"}
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(HTTPException) as exc_info:
                ProviderStub(config)
        assert exc_info.value.status_code == 500

    def test_no_api_key_env_no_error(self):
        """No api_key_env in config means no Authorization header, no error."""
        config = {"base_url": "https://api.example.com"}
        provider = ProviderStub(config)
        assert "Authorization" not in provider.headers
        assert provider.api_key is None

    def test_successful_init(self):
        """Successful init sets headers, provider_name, base_url."""
        provider = _build_provider()
        assert provider.base_url == "https://api.example.com"
        assert provider.headers["Authorization"] == "Bearer sk-test-123"
        assert provider.headers["Content-Type"] == "application/json"
        assert provider.provider_name == "stub"


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
        provider = _build_provider(config_manager=None)
        provider.config_manager = cm
        assert provider._get_timeout("openai_connect_timeout", 10.0) == 42.0

    def test_without_config_manager(self):
        """Without config_manager, returns default_value."""
        provider = _build_provider(config_manager=None)
        assert provider._get_timeout("openai_connect_timeout", 10.0) == 10.0

    def test_config_manager_missing_attr(self):
        """config_manager exists but lacks the attribute, returns default."""
        cm = MagicMock(spec=[])  # empty spec, no attributes
        provider = _build_provider(config_manager=None)
        provider.config_manager = cm
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
        assert detail["error"]["metadata"]["provider_name"] == "stub"
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
        """Inherits connect/pool from the owned client when not specified."""
        provider = _build_provider()
        client_timeout = provider.client.timeout
        timeout = provider._create_timeout(read=99.0)
        assert timeout.connect == client_timeout.connect
        assert timeout.pool == client_timeout.pool
        assert timeout.read == 99.0
        assert timeout.write is None   # default when not specified


# ===================================================================
# Client ownership & aclose
# ===================================================================

class TestClientOwnership:

    def test_provider_owns_real_client(self):
        """Provider constructs its own httpx.AsyncClient on init."""
        provider = _build_provider()
        assert isinstance(provider.client, httpx.AsyncClient)
        assert not provider.client.is_closed

    def test_client_limits_from_config_manager(self):
        """Client timeout config is derived from config_manager env-backed properties."""
        cm = MagicMock()
        cm.httpx_max_connections = 42
        cm.httpx_max_keepalive_connections = 7
        cm.httpx_connect_timeout = 12.0
        cm.httpx_read_timeout = 33.0
        cm.httpx_pool_timeout = 4.0
        provider = _build_provider(config_manager=cm)
        assert provider.client.timeout.connect == 12.0
        assert provider.client.timeout.read == 33.0
        assert provider.client.timeout.pool == 4.0

    @pytest.mark.asyncio
    async def test_aclose_closes_client(self):
        """aclose() closes the owned client."""
        provider = _build_provider()
        await provider.aclose()
        assert provider.client.is_closed

    @pytest.mark.asyncio
    async def test_aclose_idempotent(self):
        """aclose() is safe to call multiple times."""
        provider = _build_provider()
        await provider.aclose()
        await provider.aclose()  # no error
        assert provider.client.is_closed


# ===================================================================
# list_models / get_model
# ===================================================================

from src.providers.openai import OpenAICompatibleProvider


def _build_openai_provider(config_manager=None):
    config = {"base_url": "https://api.example.com", "api_key_env": "TEST_API_KEY"}
    with patch.dict("os.environ", {"TEST_API_KEY": "sk-test-123"}, clear=False):
        return OpenAICompatibleProvider(config, config_manager=config_manager)


class TestListModels:

    @pytest.mark.asyncio
    async def test_list_models_happy_path(self):
        """list_models calls GET /models and returns the JSON body."""
        provider = _build_openai_provider()
        provider._make_request = AsyncMock(return_value={"data": [{"id": "gpt-4"}]})
        result = await provider.list_models(request_id="req-1")
        provider._make_request.assert_called_once_with(
            method="GET", path="/models", request_id="req-1"
        )
        assert result == {"data": [{"id": "gpt-4"}]}

    @pytest.mark.asyncio
    async def test_list_maps_provider_error(self):
        """list_models propagates provider errors via _make_request."""
        provider = _build_openai_provider()
        provider._make_request = AsyncMock(side_effect=HTTPException(status_code=502, detail="bad"))
        with pytest.raises(HTTPException) as exc_info:
            await provider.list_models(request_id="req-1")
        assert exc_info.value.status_code == 502


class TestGetModel:

    @pytest.mark.asyncio
    async def test_get_model_found(self):
        """get_model returns the matching model metadata."""
        provider = _build_openai_provider()
        provider.list_models = AsyncMock(return_value={
            "data": [{"id": "gpt-4", "context_length": 8192}]
        })
        result = await provider.get_model("gpt-4", request_id="req-1")
        assert result == {"id": "gpt-4", "context_length": 8192}

    @pytest.mark.asyncio
    async def test_get_model_not_found_returns_empty(self):
        """get_model returns {} when the model is not in the provider list."""
        provider = _build_openai_provider()
        provider.list_models = AsyncMock(return_value={"data": [{"id": "other"}]})
        result = await provider.get_model("gpt-4", request_id="req-1")
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_model_provider_error_propagates(self):
        """get_model propagates errors from list_models."""
        provider = _build_openai_provider()
        provider.list_models = AsyncMock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(httpx.ConnectError):
            await provider.get_model("gpt-4", request_id="req-1")


# ===================================================================
# Per-provider concurrency limit (_acquire_slot / semaphore)
# ===================================================================

class TestConcurrencyLimit:
    """Tests for the per-provider max_concurrent semaphore gate."""

    def test_no_semaphore_when_max_concurrent_unset(self):
        """Provider without max_concurrent has _semaphore is None."""
        provider = _build_provider()
        assert provider._semaphore is None
        assert provider._max_concurrent is None

    def test_semaphore_created_when_max_concurrent_set(self):
        """Provider with max_concurrent creates an asyncio.Semaphore."""
        provider = _build_limited_provider(2)
        assert provider._max_concurrent == 2
        assert provider._semaphore is not None

    def test_max_concurrent_non_positive_disables_limit(self):
        """Non-positive / non-int max_concurrent disables the limit."""
        provider = _build_limited_provider(0)
        assert provider._semaphore is None
        assert provider._max_concurrent is None

    @pytest.mark.asyncio
    async def test_no_limit_requests_run_concurrently(self):
        """Without max_concurrent, two requests run concurrently."""
        provider = _build_provider()
        started = [asyncio.Event(), asyncio.Event()]
        release = asyncio.Event()
        idx = [0]

        async def post(*a, **k):
            i = idx[0]
            idx[0] += 1
            started[i].set()
            await release.wait()
            return _mock_response()

        provider.client.post = post
        t1 = asyncio.create_task(provider._make_request("POST", "/x", request_id="r1"))
        t2 = asyncio.create_task(provider._make_request("POST", "/x", request_id="r2"))
        await asyncio.wait_for(asyncio.gather(started[0].wait(), started[1].wait()), timeout=2)
        release.set()
        r1, r2 = await asyncio.gather(t1, t2)
        assert r1 == {"ok": True}
        assert r2 == {"ok": True}

    @pytest.mark.asyncio
    async def test_limit_queues_second_request(self):
        """max_concurrent=1: second request waits until the first releases its slot."""
        provider = _build_limited_provider(1, config_manager=_make_cm())
        started = [asyncio.Event(), asyncio.Event()]
        release = [asyncio.Event(), asyncio.Event()]
        idx = [0]

        async def post(*a, **k):
            i = idx[0]
            idx[0] += 1
            started[i].set()
            await release[i].wait()
            return _mock_response()

        provider.client.post = post
        t1 = asyncio.create_task(provider._make_request("POST", "/x", request_id="r1"))
        await asyncio.wait_for(started[0].wait(), timeout=2)

        t2 = asyncio.create_task(provider._make_request("POST", "/x", request_id="r2"))
        await asyncio.sleep(0.05)
        assert not started[1].is_set()  # queued, not running

        release[0].set()  # first finishes → slot freed
        await asyncio.wait_for(started[1].wait(), timeout=2)
        release[1].set()
        await asyncio.gather(t1, t2)

    @pytest.mark.asyncio
    async def test_queue_timeout_returns_503(self):
        """Queued request exceeding queue_wait_timeout fails fast with 503."""
        provider = _build_limited_provider(1, config_manager=_make_cm(queue_wait_timeout=0.05))
        first_release = asyncio.Event()
        started = [asyncio.Event(), asyncio.Event()]
        idx = [0]

        async def post(*a, **k):
            i = idx[0]
            idx[0] += 1
            started[i].set()
            if i == 0:
                await first_release.wait()
            return _mock_response()

        provider.client.post = post
        t1 = asyncio.create_task(provider._make_request("POST", "/x", request_id="r1"))
        await asyncio.wait_for(started[0].wait(), timeout=2)

        t2 = asyncio.create_task(provider._make_request("POST", "/x", request_id="r2"))
        with pytest.raises(HTTPException) as exc_info:
            await t2
        assert exc_info.value.status_code == 503

        first_release.set()
        await t1

    @pytest.mark.asyncio
    async def test_queue_timeout_does_not_leak_slot(self):
        """A 503 from queue timeout must not acquire/release a slot (no double-release)."""
        provider = _build_limited_provider(1, config_manager=_make_cm(queue_wait_timeout=0.02))
        blocker = asyncio.Event()
        running = asyncio.Event()

        async def post(*a, **k):
            running.set()
            await blocker.wait()
            return _mock_response()

        provider.client.post = post
        t1 = asyncio.create_task(provider._make_request("POST", "/x", request_id="r1"))
        await asyncio.wait_for(running.wait(), timeout=2)

        with pytest.raises(HTTPException):
            await provider._make_request("POST", "/x", request_id="r2")

        # Semaphore value must still be 0 (first call holds it; the timed-out one never acquired).
        assert provider._semaphore._value == 0
        blocker.set()
        await t1
        assert provider._semaphore._value == 1

    @pytest.mark.asyncio
    async def test_stream_slot_released_on_completion(self):
        """After a stream finishes, the slot is released; a second stream starts at once."""
        provider = _build_limited_provider(1, config_manager=_make_cm())

        async def inner(client, url, body, rid):
            yield b"a"
            yield b"b"

        provider._stream_request_inner = inner
        chunks = []
        async for c in provider._stream_request(provider.client, "/x", {}, "r1"):
            chunks.append(c)
        assert chunks == [b"a", b"b"]
        assert provider._semaphore._value == 1

        # second stream must start immediately (slot was released)
        second_started = asyncio.Event()

        async def inner2(client, url, body, rid):
            second_started.set()
            yield b"c"

        provider._stream_request_inner = inner2
        out = []
        async for c in provider._stream_request(provider.client, "/x", {}, "r2"):
            out.append(c)
        assert second_started.is_set()
        assert out == [b"c"]

    @pytest.mark.asyncio
    async def test_stream_slot_released_on_early_close(self):
        """aclose() mid-stream releases the slot."""
        provider = _build_limited_provider(1, config_manager=_make_cm())
        gate = asyncio.Event()

        async def inner(client, url, body, rid):
            yield b"a"
            await gate.wait()
            yield b"b"

        provider._stream_request_inner = inner
        gen = provider._stream_request(provider.client, "/x", {}, "r1")
        first = await gen.__anext__()
        assert first == b"a"
        await gen.aclose()
        assert provider._semaphore._value == 1  # released on close

    @pytest.mark.asyncio
    async def test_stream_slot_released_on_exception(self):
        """An exception inside the stream releases the slot."""
        provider = _build_limited_provider(1, config_manager=_make_cm())

        async def inner(client, url, body, rid):
            yield b"a"
            raise RuntimeError("boom")

        provider._stream_request_inner = inner
        gen = provider._stream_request(provider.client, "/x", {}, "r1")
        first = await gen.__anext__()
        assert first == b"a"
        with pytest.raises(RuntimeError):
            await gen.__anext__()
        assert provider._semaphore._value == 1

    @pytest.mark.asyncio
    async def test_retry_holds_slot_across_attempts(self):
        """The slot is held across a 429 retry; released once after success."""
        provider = _build_limited_provider(1, config_manager=None)  # None → hardcoded retry defaults
        seen_values = []
        calls = [0]

        async def post(*a, **k):
            calls[0] += 1
            seen_values.append(provider._semaphore._value)
            if calls[0] == 1:
                resp = MagicMock()
                resp.status_code = 429
                resp.text = "rate limited"
                resp.json.side_effect = json.JSONDecodeError("", "", 0)
                raise httpx.HTTPStatusError("429", request=MagicMock(spec=httpx.Request), response=resp)
            return _mock_response()

        provider.client.post = post
        with patch("src.providers.base.asyncio.sleep", new_callable=AsyncMock):
            result = await provider._make_request("POST", "/x", request_id="r1")

        assert result == {"ok": True}
        assert calls[0] == 2
        # Slot value was 0 during BOTH attempts (held across retry).
        assert seen_values == [0, 0]
        # Released exactly once after success.
        assert provider._semaphore._value == 1
