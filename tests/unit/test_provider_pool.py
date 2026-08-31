"""Unit tests for src/providers/pool.py — ProviderPool component.

The pool (httpx client construction, concurrency gate, in-flight accounting,
graceful drain) is exercised directly, without a whole provider around it.
"""

import asyncio

import httpx
import pytest
from fastapi import HTTPException

from src.core.config_manager import Settings
from src.providers.pool import ProviderPool


def _pool(max_concurrent=None, **settings_overrides) -> ProviderPool:
    return ProviderPool(settings=Settings(**settings_overrides), provider_name="stub",
                        max_concurrent=max_concurrent)


# ===================================================================
# Construction
# ===================================================================

class TestPoolConstruction:

    def test_owns_real_client(self):
        pool = _pool()
        assert isinstance(pool.client, httpx.AsyncClient)
        assert not pool.client.is_closed

    def test_limits_from_settings(self):
        pool = _pool(httpx_max_connections=42, httpx_max_keepalive_connections=7,
                     httpx_connect_timeout=12.0, httpx_read_timeout=33.0,
                     httpx_pool_timeout=4.0)
        assert pool.client.timeout.connect == 12.0
        assert pool.client.timeout.read == 33.0
        assert pool.client.timeout.pool == 4.0

    def test_proxy_forwarded_to_client(self):
        pool = ProviderPool(settings=Settings(), provider_name="stub",
                            proxy="socks5://proxy.red:1331")
        assert pool.proxy == "socks5://proxy.red:1331"
        assert isinstance(pool.client, httpx.AsyncClient)

    def test_no_semaphore_when_max_concurrent_unset(self):
        pool = _pool()
        assert pool._semaphore is None
        assert pool._max_concurrent is None

    def test_semaphore_created_when_max_concurrent_set(self):
        pool = _pool(max_concurrent=2)
        assert pool._max_concurrent == 2
        assert isinstance(pool._semaphore, asyncio.Semaphore)

    def test_non_positive_max_concurrent_disables_limit(self):
        pool = _pool(max_concurrent=0)
        assert pool._semaphore is None
        assert pool._max_concurrent is None

    def test_starts_idle_and_open(self):
        pool = _pool()
        assert pool._inflight == 0
        assert pool._idle.is_set()
        assert pool._closed is False


# ===================================================================
# Slot accounting and concurrency gate
# ===================================================================

class TestSlotAccounting:

    @pytest.mark.asyncio
    async def test_acquire_counts_inflight_and_releases(self):
        pool = _pool()
        async with pool._acquire_slot("r1"):
            assert pool._inflight == 1
            assert not pool._idle.is_set()
        assert pool._inflight == 0
        assert pool._idle.is_set()

    @pytest.mark.asyncio
    async def test_slot_released_on_exception(self):
        pool = _pool()
        with pytest.raises(RuntimeError):
            async with pool._acquire_slot("r1"):
                raise RuntimeError("boom")
        assert pool._inflight == 0
        assert pool._idle.is_set()

    @pytest.mark.asyncio
    async def test_slot_released_on_generator_close(self):
        """A consumer abandoning an async generator frees its slot (client disconnect)."""
        pool = _pool(max_concurrent=1)

        async def gen():
            async with pool._acquire_slot("r1"):
                yield b"a"
                await asyncio.Event().wait()

        g = gen()
        assert await g.__anext__() == b"a"
        await g.aclose()
        assert pool._semaphore._value == 1
        assert pool._inflight == 0

    @pytest.mark.asyncio
    async def test_unlimited_slots_run_concurrently(self):
        pool = _pool()
        entered = asyncio.Event()

        async def hold():
            async with pool._acquire_slot("r"):
                entered.set()
                await asyncio.sleep(0.05)

        await asyncio.gather(hold(), hold())
        assert entered.is_set()
        assert pool._inflight == 0

    @pytest.mark.asyncio
    async def test_limited_slots_queue(self):
        """max_concurrent=1: a second holder waits for the first to release."""
        pool = _pool(max_concurrent=1)
        release = asyncio.Event()
        second_entered = asyncio.Event()

        async def first():
            async with pool._acquire_slot("r1"):
                await release.wait()

        async def second():
            async with pool._acquire_slot("r2"):
                second_entered.set()

        t1 = asyncio.create_task(first())
        await asyncio.sleep(0.05)
        t2 = asyncio.create_task(second())
        await asyncio.sleep(0.05)
        assert not second_entered.is_set()  # queued, not running

        release.set()
        await asyncio.wait_for(t1, timeout=2)
        await asyncio.wait_for(asyncio.wait_for(t2, timeout=2), timeout=2)
        assert second_entered.is_set()

    @pytest.mark.asyncio
    async def test_queue_timeout_503(self):
        """A queued request exceeding queue_wait_timeout fails fast with 503."""
        pool = _pool(max_concurrent=1, queue_wait_timeout=0.05)
        release = asyncio.Event()

        async def first():
            async with pool._acquire_slot("r1"):
                await release.wait()

        t1 = asyncio.create_task(first())
        await asyncio.sleep(0.02)

        with pytest.raises(HTTPException) as exc_info:
            async with pool._acquire_slot("r2"):
                pass
        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["error"]["metadata"]["error_code"] == "provider_concurrency_limit"

        release.set()
        await asyncio.wait_for(t1, timeout=2)

    @pytest.mark.asyncio
    async def test_queue_timeout_does_not_leak_slot(self):
        """The timed-out acquirer never took the semaphore — no double release."""
        pool = _pool(max_concurrent=1, queue_wait_timeout=0.02)
        release = asyncio.Event()

        async def first():
            async with pool._acquire_slot("r1"):
                await release.wait()

        t1 = asyncio.create_task(first())
        await asyncio.sleep(0.02)

        with pytest.raises(HTTPException):
            async with pool._acquire_slot("r2"):
                pass
        assert pool._semaphore._value == 0

        release.set()
        await asyncio.wait_for(t1, timeout=2)
        assert pool._semaphore._value == 1


# ===================================================================
# Graceful drain on aclose
# ===================================================================

class TestGracefulDrain:

    @pytest.mark.asyncio
    async def test_idle_pool_closes_immediately(self):
        pool = _pool()
        await asyncio.wait_for(pool.aclose(), timeout=1.0)
        assert pool.client.is_closed

    @pytest.mark.asyncio
    async def test_aclose_waits_for_held_slot(self):
        pool = _pool()
        release = asyncio.Event()

        async def holder():
            async with pool._acquire_slot("r1"):
                await release.wait()

        task = asyncio.create_task(holder())
        await asyncio.sleep(0.05)

        closing = asyncio.create_task(pool.aclose())
        await asyncio.sleep(0.05)
        assert not closing.done(), "aclose() closed the pool with a slot held"
        assert not pool.client.is_closed

        release.set()
        await asyncio.wait_for(task, timeout=1.0)
        await asyncio.wait_for(closing, timeout=1.0)
        assert pool.client.is_closed

    @pytest.mark.asyncio
    async def test_drain_timeout_forces_close(self):
        """A holder that never releases cannot block shutdown forever."""
        pool = _pool()
        release = asyncio.Event()

        async def holder():
            async with pool._acquire_slot("r1"):
                await release.wait()

        task = asyncio.create_task(holder())
        await asyncio.sleep(0.05)

        await asyncio.wait_for(pool.aclose(drain_timeout=0.05), timeout=1.0)
        assert pool.client.is_closed

        release.set()
        await asyncio.wait_for(task, timeout=1.0)

    @pytest.mark.asyncio
    async def test_aclose_idempotent(self):
        pool = _pool()
        await pool.aclose()
        await pool.aclose()
        assert pool.client.is_closed


# ===================================================================
# Late slot acquisitions fail fast once a pool starts closing
# ===================================================================

class TestLateAcquisitionDuringDrain:

    @pytest.mark.asyncio
    async def test_late_acquirer_gets_503_no_placeholder(self):
        """A NEW acquisition after aclose() started raises 503 whose message
        carries no `{` token and whose error_code is service_unavailable (not
        provider_concurrency_limit)."""
        pool = _pool()
        release = asyncio.Event()

        async def holder():
            async with pool._acquire_slot("r1"):
                await release.wait()

        task = asyncio.create_task(holder())
        await asyncio.sleep(0.05)

        closing = asyncio.create_task(pool.aclose())
        await asyncio.sleep(0.05)
        assert not closing.done()

        with pytest.raises(HTTPException) as exc_info:
            async with pool._acquire_slot("r2"):
                pass
        assert exc_info.value.status_code == 503
        message = exc_info.value.detail["error"]["message"]
        # The SERVICE_UNAVAILABLE template is keyed on {error_details}; a raw
        # brace means the kwarg was not supplied.
        assert "{" not in message
        assert "closing" in message
        assert exc_info.value.detail["error"]["metadata"]["error_code"] == "service_unavailable"

        release.set()
        await asyncio.wait_for(task, timeout=1.0)
        await asyncio.wait_for(closing, timeout=1.0)
        assert pool.client.is_closed

    @pytest.mark.asyncio
    async def test_queued_acquirer_rechecks_after_semaphore_wait(self):
        """A request counted BEFORE the close (so the drain waits for it) but
        still queued on the semaphore re-checks _closed after the wait and
        fails with 503 instead of proceeding on the drained pool."""
        pool = _pool(max_concurrent=1, queue_wait_timeout=5.0)
        release = asyncio.Event()

        async def holder():
            async with pool._acquire_slot("r1"):
                await release.wait()

        t1 = asyncio.create_task(holder())
        await asyncio.sleep(0.05)

        # r2 counts into _inflight and queues on the semaphore BEFORE aclose.
        t2 = asyncio.create_task(pool._acquire_slot("r2").__aenter__())
        await asyncio.sleep(0.05)
        assert not t2.done()

        closing = asyncio.create_task(pool.aclose())
        await asyncio.sleep(0.05)

        release.set()  # holder finishes → r2's semaphore wait completes → re-check
        with pytest.raises(HTTPException) as exc_info:
            await asyncio.wait_for(t2, timeout=1.0)
        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["error"]["metadata"]["error_code"] == "service_unavailable"

        await asyncio.wait_for(t1, timeout=1.0)
        await asyncio.wait_for(closing, timeout=1.0)
        assert pool.client.is_closed
