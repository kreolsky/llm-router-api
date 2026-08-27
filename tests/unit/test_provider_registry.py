"""Unit tests for src/providers/__init__.py — provider registry & cache."""

from unittest.mock import AsyncMock, patch

import pytest

import src.providers as provider_registry
from src.providers import (
    clear_provider_cache_async,
    get_provider_instance,
    rebuild_provider_cache,
)


@pytest.fixture(autouse=True)
def reset_cache():
    """Ensure a clean cache (and a fresh lock state) between tests."""
    provider_registry._provider_cache.clear()
    yield
    provider_registry._provider_cache.clear()


def _make_config():
    return {"type": "openai", "base_url": "https://api.example.com", "api_key_env": "TEST_API_KEY"}


def _cm():
    from types import SimpleNamespace
    return SimpleNamespace(
        httpx_max_connections=100,
        httpx_max_keepalive_connections=20,
        httpx_connect_timeout=60.0,
        httpx_read_timeout=60.0,
        httpx_pool_timeout=5.0,
    )


class TestGetProviderInstance:

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_caches_by_provider_name(self):
        """Same provider_name returns the same cached instance."""
        cfg = _make_config()
        first = await get_provider_instance("alpha", cfg)
        second = await get_provider_instance("alpha", cfg)
        assert first is second

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_different_names_different_instances(self):
        """Different provider names get distinct instances."""
        cfg = _make_config()
        a = await get_provider_instance("alpha", cfg)
        b = await get_provider_instance("beta", cfg)
        assert a is not b

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_unknown_type_raises(self):
        """Unknown provider type raises via create_error."""
        cfg = {"type": "unknown", "base_url": "https://x.example.com"}
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            await get_provider_instance("alpha", cfg)

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_concurrent_lookups_build_once(self):
        """Concurrent get_provider_instance for an uncached provider returns the
        same instance (no duplicate build / orphaned pool)."""
        import asyncio
        cfg = _make_config()
        provider_registry._provider_cache.clear()

        async def get():
            return await get_provider_instance("gamma", cfg)

        inst1, inst2 = await asyncio.gather(get(), get())
        assert inst1 is inst2
        assert "gamma" in provider_registry._provider_cache


class TestClearProviderCacheAsync:

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_async_close_awaits_aclose_before_clear(self):
        """clear_provider_cache_async awaits every aclose then clears the cache."""
        cfg = _make_config()
        inst = await get_provider_instance("alpha", cfg)
        inst.aclose = AsyncMock()
        await clear_provider_cache_async()
        inst.aclose.assert_awaited_once()
        assert provider_registry._provider_cache == {}

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_async_close_suppresses_one_failure(self):
        """A failing aclose does not block the rest from closing."""
        cfg = _make_config()
        bad = await get_provider_instance("bad", cfg)
        good = await get_provider_instance("good", cfg)
        bad.aclose = AsyncMock(side_effect=RuntimeError("boom"))
        good.aclose = AsyncMock()
        await clear_provider_cache_async()  # must not raise
        bad.aclose.assert_awaited_once()
        good.aclose.assert_awaited_once()
        assert provider_registry._provider_cache == {}


class TestRebuildProviderCache:

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_rebuild_populates_cache(self):
        """A successful rebuild caches every configured provider."""
        config = {"providers": {"ok": _make_config()}}
        await rebuild_provider_cache(config, _cm())
        assert "ok" in provider_registry._provider_cache

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_rebuild_failure_leaves_old_cache_and_lists_all(self):
        """On failure, the old cache is retained and all failures are reported."""
        # Seed the cache with a good provider
        await rebuild_provider_cache({"providers": {"ok": _make_config()}}, _cm())
        old_instance = provider_registry._provider_cache["ok"]

        bad = {
            "broken-a": {"type": "openai", "base_url": "https://a.example.com", "api_key_env": "MISSING_A"},
            "broken-b": {"type": "openai", "base_url": "https://b.example.com", "api_key_env": "MISSING_B"},
        }
        with patch.dict("os.environ", {}, clear=True), pytest.raises(RuntimeError) as exc_info:
            await rebuild_provider_cache({"providers": bad}, _cm())
        msg = str(exc_info.value)
        assert "broken-a" in msg
        assert "broken-b" in msg
        # Old cache retained
        assert "ok" in provider_registry._provider_cache
        assert provider_registry._provider_cache["ok"] is old_instance

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_rebuild_closes_old_pools_in_background(self):
        """A successful rebuild schedules aclose on previously cached instances."""
        await rebuild_provider_cache({"providers": {"ok": _make_config()}}, _cm())
        old_instance = provider_registry._provider_cache["ok"]
        old_instance.aclose = AsyncMock()

        # Rebuild with the same config → old instance should be closed
        await rebuild_provider_cache({"providers": {"ok": _make_config()}}, _cm())
        # Background close is scheduled via ensure_future; let it run
        import asyncio
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        old_instance.aclose.assert_awaited_once()
