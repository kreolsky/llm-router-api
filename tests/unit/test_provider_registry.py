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
    """A lookup, never a build: the published cache is the only source."""

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_returns_the_published_instance(self):
        """Every configured provider resolves to the instance publish put in
        the cache, and repeated lookups return that same object."""
        config = {"providers": {"alpha": _make_config(), "beta": _make_config()}}
        await _seed_cache(config, Settings())

        for name in config["providers"]:
            first = await get_provider_instance(name)
            assert first is provider_registry._provider_cache[name]
            assert first is await get_provider_instance(name)

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_miss_raises_provider_not_found_and_builds_nothing(self):
        """The principal that must be REFUSED: a name absent from the published
        cache. A lazy build here is what used to resurrect a provider the
        operator had just deleted (see the INVARIANT on get_provider_instance)."""
        from fastapi import HTTPException
        await _seed_cache({"providers": {"alpha": _make_config()}}, Settings())

        with pytest.raises(HTTPException) as exc_info:
            await get_provider_instance("gone")
        assert exc_info.value.status_code == 404
        assert "gone" not in provider_registry._provider_cache

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_unknown_type_is_refused_at_prepare(self):
        """An unknown provider type fails the build, so it never reaches the
        cache — the lookup is not where the type is validated."""
        with pytest.raises(RuntimeError) as exc_info:
            await prepare_provider_cache(
                {"providers": {"alpha": {"type": "unknown", "base_url": "https://x.example.com"}}},
                Settings(),
            )
        assert "alpha" in str(exc_info.value)
        assert provider_registry._staged_cache is None


class TestClearProviderCacheAsync:

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_async_close_awaits_aclose_before_clear(self):
        """clear_provider_cache_async awaits every aclose then clears the cache."""
        await _seed_cache({"providers": {"alpha": _make_config()}}, Settings())
        inst = provider_registry._provider_cache["alpha"]
        inst.aclose = AsyncMock()
        await clear_provider_cache_async()
        inst.aclose.assert_awaited_once()
        assert provider_registry._provider_cache == {}

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_async_close_suppresses_one_failure(self):
        """A failing aclose does not block the rest from closing."""
        await _seed_cache({"providers": {"bad": _make_config(), "good": _make_config()}}, Settings())
        bad = provider_registry._provider_cache["bad"]
        good = provider_registry._provider_cache["good"]
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
    async def test_removed_provider_cannot_be_resurrected_around_publish(self):
        """A request that resolved its provider_config before the reload cannot
        put the removed provider back — on either side of the publish. Before,
        the instance it built landed in the old cache and went out with it;
        now the lookup refuses outright."""
        from fastapi import HTTPException
        await _seed_cache(
            {"providers": {"kept": _make_config(), "doomed": _make_config()}}, Settings())

        # New config drops "doomed"; prepare stages the shrunken cache.
        await prepare_provider_cache({"providers": {"kept": _make_config()}}, Settings())

        # Mid-reload, the stale resolution still finds the live (old) instance.
        assert await get_provider_instance("doomed") is provider_registry._provider_cache["doomed"]

        await publish_provider_cache()

        # Post-publish, the same stale resolution is refused instead of rebuilt.
        with pytest.raises(HTTPException):
            await get_provider_instance("doomed")
        assert "doomed" not in provider_registry._provider_cache
        assert "kept" in provider_registry._provider_cache

    @patch.dict("os.environ", {"TEST_API_KEY": "sk-123"}, clear=False)
    @pytest.mark.asyncio
    async def test_superseded_stage_is_closed_not_leaked(self):
        """A stage whose reload never reached publish is closed when the next
        prepare replaces it — one httpx pool per provider would leak otherwise."""
        await _seed_cache({"providers": {"ok": _make_config()}}, Settings())

        await prepare_provider_cache({"providers": {"vetoed": _make_config()}}, Settings())
        stranded = provider_registry._staged_cache["vetoed"]
        stranded.aclose = AsyncMock()

        await prepare_provider_cache({"providers": {"next": _make_config()}}, Settings())

        stranded.aclose.assert_awaited_once()
        assert set(provider_registry._staged_cache) == {"next"}

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
