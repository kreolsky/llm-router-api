"""Base provider with shared HTTP, streaming, retry, and error handling logic."""
# SYSTEM: provider — base HTTP, retry, streaming and header merging
import asyncio
import contextlib
import json
import os
import time
from collections.abc import AsyncGenerator, Callable
from functools import wraps
from typing import Any

import httpx

from ..core.error_handling import ErrorType, create_error, create_provider_http_error
from ..core.identity_headers import compile_passthrough_spec
from ..core.logging import logger
from ..utils.deep_merge import deep_merge
from ..utils.mask import mask_headers


def retry_on_rate_limit(max_retries: int | None = None, base_delay: float | None = None, max_delay: float | None = None):
    """Retry decorator for 429 (Too Many Requests) with exponential backoff.

    Backoff formula: min(base_delay * 2^attempt, max_delay).
    Rate-limit detection checks both e.status_code == 429 and
    e.original_exception.response.status_code == 429 (wrapped httpx errors).
    Config is read from self.config_manager (first arg); otherwise the decorator
    args / hardcoded defaults are used.
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Try to get config_manager from the first argument (self)
            cm = args[0].config_manager if args and hasattr(args[0], 'config_manager') else None

            if cm:
                actual_max_retries = cm.provider_max_retries if max_retries is None else max_retries
                actual_base_delay = cm.provider_retry_base_delay if base_delay is None else base_delay
                actual_max_delay = cm.provider_retry_max_delay if max_delay is None else max_delay
            else:
                actual_max_retries = max_retries if max_retries is not None else 3
                actual_base_delay = base_delay if base_delay is not None else 1.0
                actual_max_delay = max_delay if max_delay is not None else 30.0

            last_exception = None
            for attempt in range(actual_max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    # Check if this is a rate limit error (429)
                    is_rate_limit = False
                    
                    # Check for HTTPException with rate limit status code
                    if hasattr(e, 'status_code') and e.status_code == 429 or hasattr(e, 'original_exception') and hasattr(e.original_exception, 'response') and e.original_exception.response.status_code == 429:
                        is_rate_limit = True
                    
                    if is_rate_limit and attempt < actual_max_retries:
                        delay = min(actual_base_delay * (2 ** attempt), actual_max_delay)
                        last_exception = e

                        logger.warning(f"Rate limit exceeded, retrying in {delay}s (attempt {attempt + 1}/{actual_max_retries})", extra={
                            "delay_seconds": delay,
                            "attempt": attempt + 1,
                            "max_retries": actual_max_retries,
                            "component": "base_provider"
                        })
                        await asyncio.sleep(delay)
                        continue
                    else:
                        raise e
            if last_exception:
                raise last_exception
            raise RuntimeError("retry_on_rate_limit: exhausted without exception")
        return wrapper
    return decorator

# INVARIANT: self.headers["Authorization"] is set once in __init__ from
# os.environ[api_key_env]. It is never replaced per-request. Client API keys
# stay in auth.py and are not propagated to providers.
class BaseProvider:
    def __init__(self, config: dict[str, Any], config_manager=None):
        """Initialize provider from config dict.

        Reads API key from the env var named by config['api_key_env'].
        Owns its own httpx.AsyncClient (per-provider connection pool). Limits
        come from config_manager (global env applied per pool).
        Reads an optional `proxy` URL (e.g. socks5://host:port) from config;
        when set, all of the provider's traffic is routed through that proxy.
        Auto-derives provider_name from class name for logging.
        Sets default Content-Type: application/json (subclasses may override before super().__init__).

        Raises:
            HTTPException: If base_url is missing or the env var for the API key is unset.
        """
        self.base_url = config.get("base_url")
        self.api_key_env = config.get("api_key_env")
        self.headers = dict(config.get("headers") or {})
        self.api_key = os.environ.get(self.api_key_env) if self.api_key_env else None
        self.config_manager = config_manager
        self.proxy = config.get("proxy")
        self.provider_name = self.__class__.__name__.replace("Provider", "").lower()
        self.headers.setdefault("Content-Type", "application/json")

        # ARCH: identity profile. `opencode`
        # stamps a static OpenCode User-Agent here (an explicit `headers:`
        # User-Agent wins over the profile); per-request session headers are
        # assembled by the service layer and arrive via extra_headers.
        # `passthrough` forwards whitelisted client headers instead; the
        # whitelist itself is data (`passthrough_headers:`, replaces the
        # default set) — see core/identity_headers.py.
        self.identity = config.get("identity")
        self.identity_version = str(config.get("identity_version") or "1.18.23")
        if self.identity not in (None, "opencode", "passthrough"):
            raise create_error(ErrorType.PROVIDER_CONFIG_ERROR,
                             error_details=f"Unknown identity profile: {self.identity!r} (expected 'opencode' or 'passthrough').",
                             provider_name=self.provider_name)
        if self.identity == "opencode":
            self.headers.setdefault("User-Agent", f"opencode/{self.identity_version}")

        raw_passthrough = config.get("passthrough_headers")
        if raw_passthrough is not None and not isinstance(raw_passthrough, list):
            raise create_error(ErrorType.PROVIDER_CONFIG_ERROR,
                               error_details="passthrough_headers must be a list of header names.",
                               provider_name=self.provider_name)
        try:
            self.passthrough_spec = compile_passthrough_spec(raw_passthrough)
        except ValueError as e:
            raise create_error(ErrorType.PROVIDER_CONFIG_ERROR,
                               error_details=str(e),
                               provider_name=self.provider_name)

        if not self.base_url:
            raise create_error(ErrorType.PROVIDER_CONFIG_ERROR,
                             error_details="Provider base_url is not configured.",
                             provider_name=self.provider_name)

        # Only set API key and Authorization header if api_key_env is provided
        if self.api_key_env:
            if not self.api_key:
                raise create_error(ErrorType.PROVIDER_CONFIG_ERROR,
                                 error_details=f"API key for {self.api_key_env} is not set in environment variables.",
                                 provider_name=self.provider_name)
            self.headers["Authorization"] = f"Bearer {self.api_key}"

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
        # never slip past a drain that already observed zero.
        self._inflight = 0
        self._idle = asyncio.Event()
        self._idle.set()

        max_concurrent = config.get("max_concurrent")
        if isinstance(max_concurrent, int) and max_concurrent > 0:
            self._semaphore = asyncio.Semaphore(max_concurrent)
            self._max_concurrent = max_concurrent
            logger.info(
                f"Provider '{self.provider_name}' concurrency limit enabled: {max_concurrent}",
                extra={"component": "base_provider", "provider_name": self.provider_name,
                       "max_concurrent": max_concurrent}
            )
        else:
            self._semaphore = None
            self._max_concurrent = None
            logger.info(
                f"Provider '{self.provider_name}' has no concurrency limit",
                extra={"component": "base_provider", "provider_name": self.provider_name}
            )

    def _build_client(self) -> httpx.AsyncClient:
        """Construct an httpx.AsyncClient using limits from config_manager.

        ARCH: per-provider proxy support. The optional `proxy` config key
        (a full URL with scheme, e.g. socks5://proxy.red:1331) is passed to
        httpx as-is; no normalization in code. `None` = direct connection
        (httpx default), so providers without the key behave unchanged.
        httpx requires the socksio extra for socks5://; an invalid/unsupported
        proxy URL surfaces as an error when the client is first used (or on the
        fail-fast startup instantiation).
        """
        if self.config_manager is not None:
            limits = httpx.Limits(
                max_connections=self.config_manager.httpx_max_connections,
                max_keepalive_connections=self.config_manager.httpx_max_keepalive_connections
            )
            timeout = httpx.Timeout(
                connect=self.config_manager.httpx_connect_timeout,
                read=self.config_manager.httpx_read_timeout,
                write=None,
                pool=self.config_manager.httpx_pool_timeout
            )
        else:
            limits = httpx.Limits()
            timeout = httpx.Timeout(connect=60.0, read=60.0, write=None, pool=5.0)
        return httpx.AsyncClient(limits=limits, timeout=timeout, proxy=self.proxy)

    async def aclose(self, drain_timeout: float | None = None) -> None:
        """Close the owned httpx.AsyncClient once in-flight requests have drained.

        Safe to call multiple times. Waits up to drain_timeout seconds (default:
        stream_read_timeout, the longest a legitimate request may run) for every
        in-flight request and stream to finish, so a config reload does not abort
        live SSE generations. On timeout the pool is closed anyway — a stuck
        request must never block shutdown forever.
        """
        if self.client is None or self.client.is_closed:
            return
        if self._inflight > 0:
            if drain_timeout is None:
                drain_timeout = self._get_timeout("stream_read_timeout", 300.0)
            try:
                await asyncio.wait_for(self._idle.wait(), timeout=drain_timeout)
            except TimeoutError:
                logger.warning(
                    f"Provider '{self.provider_name}': {self._inflight} request(s) still in flight "
                    f"after {drain_timeout}s, closing pool anyway",
                    extra={"component": "base_provider", "provider_name": self.provider_name,
                           "inflight": self._inflight},
                )
        await self.client.aclose()

    @contextlib.asynccontextmanager
    async def _acquire_slot(self, request_id: str = "unknown"):
        """Track the request as in-flight and hold a concurrency slot for its duration.

        In-flight accounting always runs (it is what aclose() drains on). The
        semaphore gate only applies when max_concurrent is configured: it waits
        up to config_manager.queue_wait_timeout for a free slot and raises 503
        SERVICE_UNAVAILABLE on timeout. Both the slot and the in-flight count are
        released in the finally block (exception-safe, and reached on generator
        close, so a client disconnect frees them too).
        """
        self._inflight += 1
        self._idle.clear()
        acquired = False
        try:
            if self._semaphore is not None:
                wait = self.config_manager.queue_wait_timeout if self.config_manager is not None else 30.0
                try:
                    await asyncio.wait_for(self._semaphore.acquire(), timeout=wait)
                    acquired = True
                except TimeoutError:
                    raise create_error(
                        ErrorType.PROVIDER_CONCURRENCY_LIMIT,
                        error_details="Concurrency limit reached for provider; retry later.",
                        request_id=request_id,
                        provider_name=self.provider_name,
                    )
            yield
        finally:
            if acquired:
                self._semaphore.release()
            self._inflight -= 1
            if self._inflight == 0:
                self._idle.set()

    def _log_provider_data(self, title: str, data: dict[str, Any], request_id: str, data_flow: str, component: str = None) -> None:
        """Log request/response data with standardized provider context."""
        if component is None:
            component = f"{self.provider_name}_provider"
        
        logger.debug_data(
            title=title,
            data=data,
            request_id=request_id,
            component=component,
            data_flow=data_flow
        )

    def _create_timeout(self, connect: float = None, read: float = None,
                        write: float = None, pool: float = None) -> httpx.Timeout:
        """
        Create an httpx.Timeout with sensible defaults from the client.

        Unspecified connect/pool values inherit from the client's timeout.
        Unspecified read/write values default to None (no timeout).
        """
        return httpx.Timeout(
            connect=connect if connect is not None else self.client.timeout.connect,
            read=read,
            write=write,
            pool=pool if pool is not None else self.client.timeout.pool
        )

    def _apply_model_config(self, request_body: dict[str, Any], provider_model_name: str,
                            model_config: dict[str, Any]) -> dict[str, Any]:
        """
        Set provider model name and merge model-level options into request body.
        """
        request_body["model"] = provider_model_name
        if options := model_config.get("options"):
            request_body = deep_merge(request_body, options)
        return request_body

    def _raise_provider_http_error(self, e: httpx.HTTPStatusError, request_id: str = "unknown") -> None:
        """Extract error message from provider response and raise HTTPException.

        Handles ResponseNotRead (streaming context where body isn't buffered).
        Logs via log_provider_error before raising.
        """
        response_text = ""
        try:
            response_text = e.response.text
        except httpx.ResponseNotRead:
            response_text = "Unable to read error response from provider"

        error_message = f"Provider API error: {e.response.status_code}"
        try:
            error_json = e.response.json()
            if "error" in error_json and isinstance(error_json["error"], dict):
                error_message = error_json["error"].get("message", error_message)
            elif "message" in error_json:
                error_message = error_json["message"]
        except (json.JSONDecodeError, ValueError, httpx.ResponseNotRead):
            error_message = response_text or error_message

        raise create_provider_http_error(
            status_code=e.response.status_code,
            message=error_message,
            provider_name=self.provider_name,
            raw=response_text,
            request_id=request_id,
            original_exception=e,
        ) from e

    def _get_timeout(self, timeout_type: str, default_value: float) -> float:
        """Read a named timeout from config_manager, falling back to default_value."""
        if self.config_manager and hasattr(self.config_manager, timeout_type):
            return getattr(self.config_manager, timeout_type)
        return default_value

    def _merge_request_headers(self, extra_headers: dict[str, str] | None) -> dict[str, str]:
        """Merge per-request extra_headers over self.headers.

        ARCH: shared by the stream and non-stream paths so both send an
        identical header set — a diverging set is itself a fingerprint.
        Authorization is never overwritten (INVARIANT above the class);
        case-insensitive duplicates of extra keys replace their base
        counterparts instead of being sent twice.
        """
        merged = dict(self.headers)
        if not extra_headers:
            return merged
        # WHY: authorization is not replaceable, so it must also survive the
        # case-insensitive duplicate elimination below.
        extra_lower = {name.lower() for name in extra_headers} - {"authorization"}
        merged = {k: v for k, v in merged.items() if k.lower() not in extra_lower}
        for name, value in extra_headers.items():
            if name.lower() == "authorization":
                continue
            merged[name] = value
        return merged

    async def _make_request(
        self,
        method: str,
        path: str,
        request_body: dict[str, Any] = None,
        extra_headers: dict[str, str] = None,
        timeout: httpx.Timeout = None,
        files: dict[str, Any] = None,
        data: dict[str, Any] = None,
        request_id: str = "unknown"
    ) -> dict[str, Any]:
        """Unified non-streaming HTTP request to provider APIs.

        Holds a per-provider concurrency slot across the whole call. The retry
        loop (on @retry_on_rate_limit on _make_request_inner) runs inside the
        held slot, so retries reuse the same slot and it is released exactly once.
        HTTPStatusError: extracts error message from provider JSON response.
        RequestError: maps to a network error. extra_headers may add non-credential
        headers (e.g. Accept) but cannot overwrite Authorization — see INVARIANT
        above the class.
        """
        async with self._acquire_slot(request_id):
            return await self._make_request_inner(
                method, path, request_body=request_body, extra_headers=extra_headers,
                timeout=timeout, files=files, data=data, request_id=request_id,
            )

    @retry_on_rate_limit()
    async def _make_request_inner(
        self,
        method: str,
        path: str,
        request_body: dict[str, Any] = None,
        extra_headers: dict[str, str] = None,
        timeout: httpx.Timeout = None,
        files: dict[str, Any] = None,
        data: dict[str, Any] = None,
        request_id: str = "unknown"
    ) -> dict[str, Any]:
        """Actual HTTP request implementation. See _make_request for the slot wrapper."""
        merged_headers = self._merge_request_headers(extra_headers)

        self._log_provider_data(
            title=f"{self.__class__.__name__} Request",
            data={
                "url": f"{self.base_url}{path}",
                "headers": mask_headers(merged_headers),
                "request_body": request_body,
                "has_files": files is not None,
                "has_data": data is not None
            },
            request_id=request_id,
            data_flow="to_provider"
        )

        try:
            if method.upper() == "POST":
                # WHY: multipart uploads (files) need httpx to set Content-Type with boundary;
                # explicit Content-Type: application/json would break the multipart encoding
                if files:
                    merged_headers.pop("Content-Type", None)

                response = await self.client.post(
                    f"{self.base_url}{path}",
                    headers=merged_headers,
                    json=request_body if not files else None,
                    files=files,
                    data=data,
                    timeout=timeout
                )
            elif method.upper() == "GET":
                response = await self.client.get(
                    f"{self.base_url}{path}",
                    headers=merged_headers,
                    params=request_body,
                    timeout=timeout
                )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            response_json = response.json()

            self._log_provider_data(
                title=f"{self.__class__.__name__} Response",
                data=response_json,
                request_id=request_id,
                data_flow="from_provider"
            )
            
            return response_json
            
        except json.JSONDecodeError as e:
            raise create_error(ErrorType.PROVIDER_INVALID_RESPONSE, original_exception=e,
                             error_details=f"Non-JSON response (status {response.status_code})",
                             request_id=request_id, provider_name=self.provider_name)
        except httpx.HTTPStatusError as e:
            self._raise_provider_http_error(e, request_id)
        except httpx.RequestError as e:
            raise create_error(ErrorType.PROVIDER_NETWORK_ERROR, original_exception=e,
                             error_details=str(e), request_id=request_id, provider_name=self.provider_name)

    async def _stream_request(self, client: httpx.AsyncClient, url_path: str,
                              request_body: dict[str, Any], request_id: str = "unknown",
                              extra_headers: dict[str, str] = None) -> AsyncGenerator[bytes, None]:
        """Async generator streaming raw bytes from a provider API.

        Holds a per-provider concurrency slot across the ENTIRE iteration by the
        downstream consumer. `async with` releases on normal completion, on
        exception, and on generator close (AClose) — so a client disconnect also
        frees the slot. extra_headers are merged exactly like in _make_request.
        """
        async with self._acquire_slot(request_id):
            async for chunk in self._stream_request_inner(client, url_path, request_body, request_id,
                                                          extra_headers):
                yield chunk

    async def _stream_request_inner(self, client: httpx.AsyncClient, url_path: str,
                              request_body: dict[str, Any], request_id: str = "unknown",
                              extra_headers: dict[str, str] = None) -> AsyncGenerator[bytes, None]:
        """Actual streaming implementation. See _stream_request for the slot wrapper.

        Uses client.stream() context manager for memory-efficient chunk iteration.
        Headers go through _merge_request_headers so the stream and non-stream
        paths send an identical set.
        Error hierarchy inside stream context:
        - HTTPStatusError with ResponseNotRead fallback for error body
        - PoolTimeout → 503 (connection pool exhausted)
        - RequestError → generic network error
        """
        merged_headers = self._merge_request_headers(extra_headers)

        self._log_provider_data(
            title="Base Provider Request",
            data={
                "url": f"{self.base_url}{url_path}",
                "headers": mask_headers(merged_headers),
                "request_body": request_body
            },
            request_id=request_id,
            data_flow="to_provider"
        )

        stream_read_timeout = self._get_timeout("stream_read_timeout", 300.0)
        stream_timeout = self._create_timeout(read=stream_read_timeout)

        logger.debug(f"Starting stream request to {url_path}", extra={
            "url": f"{self.base_url}{url_path}",
            "timeout": str(stream_timeout),
            "request_id": request_id
        })
        start_time = time.time()
        try:
            async with client.stream("POST", f"{self.base_url}{url_path}",
                                     headers=merged_headers,
                                     json=request_body,
                                     timeout=stream_timeout) as response:
                logger.debug(f"Stream response headers received after {time.time() - start_time:.2f}s", extra={
                    "status_code": response.status_code,
                    "request_id": request_id
                })

                self._log_provider_data(
                    title="Provider Response Headers",
                    data={
                        "status_code": response.status_code,
                        "headers": dict(response.headers)
                    },
                    request_id=request_id,
                    data_flow="from_provider"
                )

                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    self._raise_provider_http_error(e, request_id)

                logger.debug(f"Starting to iterate over stream chunks for {request_id}")
                async for chunk in response.aiter_bytes():
                    logger.debug(f"Provider yielded {len(chunk)} bytes", extra={
                        "request_id": request_id,
                        "chunk_size": len(chunk)
                    })
                    yield chunk
                logger.debug(f"Provider stream finished for {request_id}")
        # WHY: PoolTimeout means all connections in use, not a network failure — maps to 503
        except httpx.PoolTimeout as e:
            raise create_error(ErrorType.SERVICE_UNAVAILABLE,
                             original_exception=e,
                             error_details="Connection pool exhausted. Please retry later.",
                             request_id=request_id,
                             provider_name=self.provider_name) from e
        except httpx.RequestError as e:
            raise create_error(ErrorType.PROVIDER_NETWORK_ERROR,
                             original_exception=e,
                             error_details=str(e),
                             request_id=request_id,
                             provider_name=self.provider_name) from e
        except Exception as e:
            logger.error(f"Stream request failed after {time.time() - start_time:.2f}s: {str(e)}", extra={
                "error_type": type(e).__name__,
                "request_id": request_id
            }, exc_info=True)
            raise

    async def chat_completions(self, request_body: dict[str, Any], provider_model_name: str,
                               model_config: dict[str, Any], request_id: str = "unknown",
                               extra_headers: dict[str, str] = None) -> dict[str, Any]:
        """Non-streaming chat completion. Returns the parsed provider JSON response."""
        raise NotImplementedError

    def chat_completions_stream(self, request_body: dict[str, Any], provider_model_name: str,
                                model_config: dict[str, Any], request_id: str = "unknown",
                                extra_headers: dict[str, str] = None) -> AsyncGenerator[bytes, None]:
        """Streaming chat completion. Yields raw SSE bytes from the provider."""
        raise NotImplementedError

    async def embeddings(self, request_body: dict[str, Any], provider_model_name: str,
                         model_config: dict[str, Any], request_id: str = "unknown") -> Any:
        raise NotImplementedError

    async def list_models(self, request_id: str = "unknown") -> dict[str, Any]:
        """Return the provider's model list (raw /models response)."""
        raise NotImplementedError

    async def get_model(self, provider_model_name: str, request_id: str = "unknown") -> dict[str, Any]:
        """Return a single model's metadata, or {} if not found."""
        raise NotImplementedError

    async def transcriptions(self, request_body: dict[str, Any], provider_model_name: str,
                             model_config: dict[str, Any], request_id: str = "unknown") -> Any:
        """Transcribe audio. request_body shape:

            {"audio": {"filename": str, "content_type": str, "data": bytes},
             "params": {"language"?, "temperature"?, "response_format"?,
                        "return_timestamps"?, "prompt"?}}
        """
        raise NotImplementedError
