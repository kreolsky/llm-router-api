"""Provider-owned httpx pool: client construction, concurrency gate, graceful drain.

Extracted from BaseProvider (composition, not a base-class role) so the pool
lifecycle — drain-on-close, semaphore, late-acquirer refusal — is directly
testable without a whole provider around it.
"""
import asyncio
import contextlib

import httpx

from ..core.config_manager import Settings
from ..core.error_handling import ErrorType, create_error
from ..core.logging import logger


class ProviderPool:
    """One provider's httpx.AsyncClient plus the concurrency gate and drain accounting."""

    def __init__(self, *, settings: Settings, provider_name: str,
                 proxy: str | None = None, max_concurrent=None):
        """Build the client and the in-flight/semaphore machinery.

        settings supplies the pool limits (global env applied per pool — each
        provider instance owns its own pool, they are not shared) and
        queue_wait_timeout for the semaphore gate. max_concurrent comes from
        the provider's providers.yaml entry; only a positive int enables the
        gate. proxy is an optional full URL with scheme (e.g.
        socks5://proxy.red:1331) passed to httpx as-is; None = direct.
        """
        self.settings = settings
        self.provider_name = provider_name
        self.proxy = proxy

        # ARCH: each provider instance owns its own httpx pool. Global env limits
        # (HTTPX_MAX_CONNECTIONS, etc.) are applied per backend pool, not shared.
        self.client = self._build_client()

        # ARCH: per-instance concurrency gate (asyncio.Semaphore). Only created when
        # `max_concurrent` is a positive int; otherwise None (no limiting). The semaphore
        # is owned per-instance, so a config reload that changes max_concurrent only takes
        # effect after a config reload rebuilds the cache (semaphore is per-instance).
        # ARCH: in-flight accounting for graceful drain. A config reload swaps the
        # provider cache and closes the OLD pools, but long-lived SSE streams are
        # still reading from them — closing mid-stream aborts live generations.
        # aclose() therefore waits for _idle before closing. Counted from entry
        # into _acquire_slot (before the semaphore wait), so a queued request can
        # never slip past a drain that already observed zero. _closed flips True
        # the moment aclose() starts; _acquire_slot refuses to count new requests
        # after that (see the INVARIANT in _acquire_slot).
        self._inflight = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._closed = False

        if isinstance(max_concurrent, int) and max_concurrent > 0:
            self._semaphore = asyncio.Semaphore(max_concurrent)
            self._max_concurrent = max_concurrent
            logger.info(
                f"Provider '{self.provider_name}' concurrency limit enabled: {max_concurrent}",
                extra={"component": "provider_pool", "provider_name": self.provider_name,
                       "max_concurrent": max_concurrent}
            )
        else:
            self._semaphore = None
            self._max_concurrent = None
            logger.info(
                f"Provider '{self.provider_name}' has no concurrency limit",
                extra={"component": "provider_pool", "provider_name": self.provider_name}
            )

    def _build_client(self) -> httpx.AsyncClient:
        """Construct an httpx.AsyncClient using limits from settings.

        ARCH: per-provider proxy support. The optional `proxy` config key
        (a full URL with scheme, e.g. socks5://proxy.red:1331) is passed to
        httpx as-is; no normalization in code. `None` = direct connection
        (httpx default), so providers without the key behave unchanged.
        httpx requires the socksio extra for socks5://; an invalid/unsupported
        proxy URL surfaces as an error when the client is first used (or on the
        fail-fast startup instantiation).
        """
        limits = httpx.Limits(
            max_connections=self.settings.httpx_max_connections,
            max_keepalive_connections=self.settings.httpx_max_keepalive_connections
        )
        timeout = httpx.Timeout(
            connect=self.settings.httpx_connect_timeout,
            read=self.settings.httpx_read_timeout,
            write=None,
            pool=self.settings.httpx_pool_timeout
        )
        return httpx.AsyncClient(limits=limits, timeout=timeout, proxy=self.proxy)

    async def aclose(self, drain_timeout: float | None = None) -> None:
        """Close the owned httpx.AsyncClient once in-flight requests have drained.

        Safe to call multiple times. Waits up to drain_timeout seconds (default:
        stream_read_timeout, the longest a legitimate request may run) for every
        in-flight request and stream to finish, so a config reload does not abort
        live SSE generations. On timeout the pool is closed anyway — a stuck
        request must never block shutdown forever.

        INVARIANT: _closed is set BEFORE the drain wait starts.
        Why: the drain only awaits requests counted into _inflight by then; a
        request acquiring a slot after the drain waiter woke would run on a
        pool that closes under it. Late acquirers get a 503 from
        _acquire_slot instead.
        """
        self._closed = True
        if self.client is None or self.client.is_closed:
            return
        if self._inflight > 0:
            if drain_timeout is None:
                drain_timeout = self.settings.stream_read_timeout
            try:
                await asyncio.wait_for(self._idle.wait(), timeout=drain_timeout)
            except TimeoutError:
                logger.warning(
                    f"Provider '{self.provider_name}': {self._inflight} request(s) still in flight "
                    f"after {drain_timeout}s, closing pool anyway",
                    extra={"component": "provider_pool", "provider_name": self.provider_name,
                           "inflight": self._inflight},
                )
        await self.client.aclose()

    @contextlib.asynccontextmanager
    async def _acquire_slot(self, request_id: str = "unknown"):
        """Track the request as in-flight and hold a concurrency slot for its duration.

        In-flight accounting always runs (it is what aclose() drains on). The
        semaphore gate only applies when max_concurrent is configured: it waits
        up to settings.queue_wait_timeout for a free slot and raises 503
        SERVICE_UNAVAILABLE on timeout. Both the slot and the in-flight count are
        released in the finally block (exception-safe, and reached on generator
        close, so a client disconnect frees them too).

        INVARIANT: once aclose() has started, no new request may acquire a slot.
        Why: the drain waiter only awaits requests it could count — a late
        acquirer would enter a pool that closes under it. The check runs before
        counting into _inflight and again after the semaphore wait (a request
        queued before the close must not proceed on the drained pool either).
        Deliberately SERVICE_UNAVAILABLE with error_details="provider pool is
        closing", NOT PROVIDER_CONCURRENCY_LIMIT — the queue-timeout 503 and
        the pool-closing 503 must stay distinguishable in the stats rows.
        """
        if self._closed:
            raise self._pool_closing_error(request_id)
        self._inflight += 1
        self._idle.clear()
        acquired = False
        try:
            if self._semaphore is not None:
                wait = self.settings.queue_wait_timeout
                try:
                    await asyncio.wait_for(self._semaphore.acquire(), timeout=wait)
                    acquired = True
                except TimeoutError:
                    # from None: the semaphore wait timing out is expected
                    # control flow, fully described by the error itself.
                    raise create_error(
                        ErrorType.PROVIDER_CONCURRENCY_LIMIT,
                        error_details="Concurrency limit reached for provider; retry later.",
                        request_id=request_id,
                        provider_name=self.provider_name,
                    ) from None
                if self._closed:
                    raise self._pool_closing_error(request_id)
            yield
        finally:
            if acquired:
                self._semaphore.release()
            self._inflight -= 1
            if self._inflight == 0:
                self._idle.set()

    def _pool_closing_error(self, request_id: str):
        """503 for a request arriving while the provider pool is draining.

        error_details is always supplied: the SERVICE_UNAVAILABLE template is
        keyed on it, and omitting it would leak the raw `{error_details}`
        placeholder to the client.
        """
        return create_error(
            ErrorType.SERVICE_UNAVAILABLE,
            error_details="provider pool is closing",
            request_id=request_id,
            provider_name=self.provider_name,
        )
