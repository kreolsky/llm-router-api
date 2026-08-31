"""Unit tests for src/providers/__init__.py — provider registry & cache."""

from unittest.mock import AsyncMock, patch

import pytest

import src.providers as provider_registry
from src.core.config_manager import Settings
from src.providers import (
    _build_provider,
    clear_provider_cache_async,
    get_provider_instance,
    prepare_provider_cache,
    publish_provider_cache,
)


@pytest.fixture(autouse=True)
def reset_cache():
    """Ensure a clean cache, no staged remnant and a fresh lock state between tests."""
    provider_registry._provider_cache.clear()
    provider_registry._staged_cache = None
    yield
    provider_registry._provider_cache.clear()
    provider_registry._staged_cache = None


def _make_config():
    return {"type": "openai", "base_url": "https://api.example.com", "api_key_env": "TEST_API_KEY"}


def _settings() -> Settings:
    return Settings()


class TestBuildProviderName:
    """The factory passes the providers.yaml key down as provider_name."""

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    def test_instance_gets_real_provider_name(self):
        """_build_provider("glm", ...) → provider_name "glm": logs and startup
        errors name the actual backend, not the shared type literal."""
        instance = _build_provider("glm", _make_config(), Settings())
        assert instance.provider_name == "glm"

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    def test_direct_construction_falls_back_to_class_name(self):
        """Without provider_name the class-derived fallback applies — the same
        literal for every provider of a type, which is why the factory passes
        the config key explicitly."""
        from src.providers.openai import OpenAICompatibleProvider
        instance = OpenAICompatibleProvider(_make_config(), Settings())
        assert instance.provider_name == "openaicompatible"


class TestGetProviderInstance:

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_caches_by_provider_name(self):
        """Same provider_name returns the same cached instance."""
        cfg = _make_config()
        first = await get_provider_instance("alpha", cfg, Settings())
        second = await get_provider_instance("alpha", cfg, Settings())
        assert first is second

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_different_names_different_instances(self):
        """Different provider names get distinct instances."""
        cfg = _make_config()
        a = await get_provider_instance("alpha", cfg, Settings())
        b = await get_provider_instance("beta", cfg, Settings())
        assert a is not b

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_unknown_type_raises(self):
        """Unknown provider type raises via create_error."""
        cfg = {"type": "unknown", "base_url": "https://x.example.com"}
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            await get_provider_instance("alpha", cfg, Settings())

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_concurrent_lookups_build_once(self):
        """Concurrent get_provider_instance for an uncached provider returns the
        same instance (no duplicate build / orphaned pool)."""
        import asyncio
        cfg = _make_config()
        provider_registry._provider_cache.clear()

        async def get():
            return await get_provider_instance("gamma", cfg, Settings())

        inst1, inst2 = await asyncio.gather(get(), get())
        assert inst1 is inst2
        assert "gamma" in provider_registry._provider_cache


class TestClearProviderCacheAsync:

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_async_close_awaits_aclose_before_clear(self):
        """clear_provider_cache_async awaits every aclose then clears the cache."""
        cfg = _make_config()
        inst = await get_provider_instance("alpha", cfg, Settings())
        inst.aclose = AsyncMock()
        await clear_provider_cache_async()
        inst.aclose.assert_awaited_once()
        assert provider_registry._provider_cache == {}

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_async_close_suppresses_one_failure(self):
        """A failing aclose does not block the rest from closing."""
        cfg = _make_config()
        bad = await get_provider_instance("bad", cfg, Settings())
        good = await get_provider_instance("good", cfg, Settings())
        bad.aclose = AsyncMock(side_effect=RuntimeError("boom"))
        good.aclose = AsyncMock()
        await clear_provider_cache_async()  # must not raise
        bad.aclose.assert_awaited_once()
        good.aclose.assert_awaited_once()
        assert provider_registry._provider_cache == {}


async def _seed_cache(config, settings):
    """prepare + publish back to back — what startup and a full reload do."""
    await prepare_provider_cache(config, settings)
    await publish_provider_cache()


class TestPreparePublishProviderCache:
    """Two-phase cache rebuild: prepare stages pre-swap, publish swaps post-swap."""

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_prepare_stages_without_swapping(self):
        """prepare builds and stages the new instances; the live cache is
        untouched until publish runs."""
        config = {"providers": {"ok": _make_config()}}
        await _seed_cache(config, Settings())
        old_instance = provider_registry._provider_cache["ok"]

        await prepare_provider_cache({"providers": {"renamed": _make_config()}}, Settings())

        assert "renamed" in provider_registry._staged_cache
        assert "renamed" not in provider_registry._provider_cache
        assert provider_registry._provider_cache["ok"] is old_instance

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_publish_swaps_staged_and_drains_old(self):
        """publish swaps the staged cache in and closes the previous pools in
        the background (drain task tracked until done)."""
        import asyncio
        await _seed_cache({"providers": {"ok": _make_config()}}, Settings())
        old_instance = provider_registry._provider_cache["ok"]
        old_instance.aclose = AsyncMock()

        await prepare_provider_cache({"providers": {"ok": _make_config()}}, Settings())
        await publish_provider_cache()

        assert provider_registry._provider_cache["ok"] is not old_instance
        assert provider_registry._staged_cache is None
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        old_instance.aclose.assert_awaited_once()

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_prepare_failure_retains_cache_and_lists_all(self):
        """On failure the live cache is retained, nothing stays staged, and all
        failures are reported (collect-all fail-fast)."""
        await _seed_cache({"providers": {"ok": _make_config()}}, Settings())
        old_instance = provider_registry._provider_cache["ok"]

        bad = {
            "broken-a": {"type": "openai", "base_url": "https://a.example.com", "api_key_env": "MISSING_A"},
            "broken-b": {"type": "openai", "base_url": "https://b.example.com", "api_key_env": "MISSING_B"},
        }
        with patch.dict("os.environ", {}, clear=True), pytest.raises(RuntimeError) as exc_info:
            await prepare_provider_cache({"providers": bad}, Settings())
        msg = str(exc_info.value)
        assert "broken-a" in msg
        assert "broken-b" in msg
        assert provider_registry._provider_cache["ok"] is old_instance
        assert provider_registry._staged_cache is None

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_publish_without_prepare_is_noop(self):
        """publish with nothing staged leaves the live cache alone."""
        await _seed_cache({"providers": {"ok": _make_config()}}, Settings())
        instance = provider_registry._provider_cache["ok"]
        await publish_provider_cache()
        assert provider_registry._provider_cache["ok"] is instance

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_window_ghost_discarded_by_publish(self):
        """The reload window bug this split fixes: between the config swap and
        the cache publish, get_provider_instance may build an instance from a
        stale resolution into the OLD cache. publish must discard it along
        with the old cache — a removed provider must not survive the reload."""
        await _seed_cache(
            {"providers": {"kept": _make_config(), "doomed": _make_config()}}, Settings())

        # New config drops "doomed"; prepare stages the shrunken cache.
        await prepare_provider_cache({"providers": {"kept": _make_config()}}, Settings())

        # Window: a stale resolution re-populates the OLD cache mid-reload.
        await get_provider_instance("doomed", _make_config(), Settings())
        assert "doomed" in provider_registry._provider_cache

        await publish_provider_cache()
        assert "doomed" not in provider_registry._provider_cache
        assert "kept" in provider_registry._provider_cache

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_publish_drain_task_tracked_until_done(self):
        """The background close task is referenced until it finishes.

        asyncio only keeps a weak reference to a running task: an unreferenced
        ensure_future result can be garbage-collected mid-flight, dropping the
        pool closes it was carrying. Mirrors the _usage_tasks pattern in
        src/core/usage_db/writer.py.
        """
        import asyncio
        await _seed_cache({"providers": {"ok": _make_config()}}, Settings())
        old_instance = provider_registry._provider_cache["ok"]

        release = asyncio.Event()

        async def slow_aclose(drain_timeout=None):
            await release.wait()

        old_instance.aclose = slow_aclose

        await prepare_provider_cache({"providers": {"ok": _make_config()}}, Settings())
        await publish_provider_cache()
        assert provider_registry._drain_tasks, "drain task must be tracked while pools close"
        tracked = next(iter(provider_registry._drain_tasks))
        assert not tracked.done()

        release.set()
        await asyncio.wait_for(tracked, timeout=2)
        await asyncio.sleep(0)
        assert not provider_registry._drain_tasks, "done drain task must discard itself"
