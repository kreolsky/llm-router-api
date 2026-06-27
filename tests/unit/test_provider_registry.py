"""Unit tests for src/providers/__init__.py — provider registry & cache."""

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

import src.providers as provider_registry
from src.providers import get_provider_instance, clear_provider_cache, clear_provider_cache_async
from src.providers.base import BaseProvider


@pytest.fixture(autouse=True)
def reset_cache():
    """Ensure a clean cache between tests."""
    provider_registry._provider_cache.clear()
    yield
    provider_registry._provider_cache.clear()


def _make_config():
    return {"type": "openai", "base_url": "https://api.example.com", "api_key_env": "TEST_API_KEY"}


class TestGetProviderInstance:

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    def test_caches_by_provider_name(self):
        """Same provider_name returns the same cached instance."""
        cfg = _make_config()
        first = get_provider_instance("alpha", cfg)
        second = get_provider_instance("alpha", cfg)
        assert first is second

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    def test_different_names_different_instances(self):
        """Different provider names get distinct instances."""
        cfg = _make_config()
        a = get_provider_instance("alpha", cfg)
        b = get_provider_instance("beta", cfg)
        assert a is not b

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    def test_unknown_type_raises(self):
        """Unknown provider type raises via create_error."""
        cfg = {"type": "unknown", "base_url": "https://x.example.com"}
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            get_provider_instance("alpha", cfg)


class TestClearProviderCache:

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    def test_clear_calls_aclose_on_instances(self):
        """clear_provider_cache closes each cached provider's client."""
        cfg = _make_config()
        inst = get_provider_instance("alpha", cfg)
        inst.aclose = AsyncMock()
        # No running loop → asyncio.run path executes aclose
        clear_provider_cache()
        inst.aclose.assert_awaited_once()
        assert provider_registry._provider_cache == {}

    def test_clear_empty_cache_noop(self):
        """Clearing an empty cache is a no-op."""
        provider_registry._provider_cache.clear()
        clear_provider_cache()  # must not raise
        assert provider_registry._provider_cache == {}


class TestClearProviderCacheAsync:

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_async_close_awaits_aclose_before_clear(self):
        """clear_provider_cache_async awaits every aclose then clears the cache."""
        cfg = _make_config()
        inst = get_provider_instance("alpha", cfg)
        inst.aclose = AsyncMock()
        await clear_provider_cache_async()
        inst.aclose.assert_awaited_once()
        assert provider_registry._provider_cache == {}

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_async_close_suppresses_one_failure(self):
        """A failing aclose does not block the rest from closing."""
        cfg = _make_config()
        bad = get_provider_instance("bad", cfg)
        good = get_provider_instance("good", cfg)
        bad.aclose = AsyncMock(side_effect=RuntimeError("boom"))
        good.aclose = AsyncMock()
        await clear_provider_cache_async()  # must not raise
        bad.aclose.assert_awaited_once()
        good.aclose.assert_awaited_once()
        assert provider_registry._provider_cache == {}
