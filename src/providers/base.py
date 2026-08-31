"""Base provider with shared HTTP, streaming, retry, and error handling logic."""
# SYSTEM: provider — base HTTP, retry, streaming and header merging
import asyncio
import json
import os
import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from ..core.config_manager import Settings
from ..core.error_handling import ErrorType, create_error, create_provider_http_error
from ..core.header_policy import FORBIDDEN_STATIC_HEADERS
from ..core.logging import logger
from ..utils.deep_merge import deep_merge
from ..utils.mask import mask_headers
from .pool import ProviderPool


def _is_rate_limit_error(e: BaseException) -> bool:
    """429 detection for the retry loop in _make_request_inner.

    Either the exception itself carries status 429, or it wraps one
    (original_exception.response.status_code == 429, wrapped httpx errors) —
    the wrapped response may be None, which must mean "not a rate limit",
    not a crash.
    """
    if hasattr(e, 'status_code') and e.status_code == 429:
        return True
    original = getattr(e, 'original_exception', None)
    response = getattr(original, 'response', None)
    return response is not None and getattr(response, 'status_code', None) == 429


# INVARIANT: self.headers["Authorization"] is set once in __init__ from
# os.environ[api_key_env]. It is never replaced per-request. Client API keys
# stay in auth.py and are not propagated to providers.
class BaseProvider:
    def __init__(self, config: dict[str, Any], settings: Settings, provider_name: str | None = None):
        """Initialize provider from config dict.

        Reads API key from the env var named by config['api_key_env'].
        Composes a ProviderPool: its own httpx.AsyncClient (per-provider
        connection pool), concurrency gate and drain accounting. Limits
        come from settings (global env applied per pool).
        Reads an optional `proxy` URL (e.g. socks5://host:port) from config;
        when set, all of the provider's traffic is routed through that proxy.
        provider_name is the providers.yaml dict key (used in logs and
        startup-validation errors); without it the name is derived from the
        class name as a fallback (all type-"openai" providers would log as
        "openai", hiding the actual backend).
        Sets default Content-Type: application/json (subclasses may override before super().__init__).

        Raises:
            HTTPException: If base_url is missing or the env var for the API key is unset.
        """
        self.base_url = config.get("base_url")
        self.api_key_env = config.get("api_key_env")
        self.headers = dict(config.get("headers") or {})
        self.api_key = os.environ.get(self.api_key_env) if self.api_key_env else None
        self.settings = settings
        self.proxy = config.get("proxy")
        self.provider_name = provider_name or self.__class__.__name__.replace("Provider", "").lower()

        # ARCH: single identity mode. `passthrough` forwards every client
        # header upstream verbatim minus the denylist
        # (core/header_policy.py); the headers are assembled by the service
        # layer per request and arrive via extra_headers.
        self.identity = config.get("identity")
        if self.identity not in (None, "passthrough"):
            raise create_error(ErrorType.PROVIDER_CONFIG_ERROR,
                             error_details=f"Unknown identity profile: {self.identity!r} (expected 'passthrough').",
                             provider_name=self.provider_name)

        # Static `headers:` validation — fail at construction (startup
        # validation), not on the first request. Runs BEFORE the code-owned
        # Content-Type default below, so only operator-authored entries are
        # checked.
        for name, value in self.headers.items():
            if not isinstance(name, str) or not name.strip() or not isinstance(value, str):
                raise create_error(ErrorType.PROVIDER_CONFIG_ERROR,
                                 error_details=f"headers entries must be 'name: value' strings, got {name!r}: {value!r}.",
                                 provider_name=self.provider_name)
            if name.lower() in FORBIDDEN_STATIC_HEADERS:
                raise create_error(ErrorType.PROVIDER_CONFIG_ERROR,
                                 error_details=f"headers may not set {name!r} (Authorization comes from api_key_env; transport/hop-by-hop headers are owned by the router).",
                                 provider_name=self.provider_name)
        self.headers.setdefault("Content-Type", "application/json")

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

        # ARCH: the httpx pool is a composed component (providers/pool.py), not a
        # base-class role — client construction, the concurrency gate and the
        # graceful-drain invariants live there, directly testable.
        self.pool = ProviderPool(settings=settings, provider_name=self.provider_name,
                                 proxy=self.proxy, max_concurrent=config.get("max_concurrent"))

    async def aclose(self, drain_timeout: float | None = None) -> None:
        """Close the owned pool once in-flight requests have drained.

        Thin delegate to the composed ProviderPool (see there for the drain
        contract); kept on the provider because the registry closes providers.
        """
        await self.pool.aclose(drain_timeout)

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
        Create an httpx.Timeout with the client's defaults for anything unspecified.

        WHY: every unspecified field — read and write included, exactly like
        connect/pool — inherits from the client's timeout. Passing None would
        mean "no timeout", letting a silent upstream hold its concurrency slot
        and in-flight count until the aclose() drain timeout.
        """
        client_timeout = self.pool.client.timeout
        return httpx.Timeout(
            connect=connect if connect is not None else client_timeout.connect,
            read=read if read is not None else client_timeout.read,
            write=write if write is not None else client_timeout.write,
            pool=pool if pool is not None else client_timeout.pool
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

    # WHY noqa ASYNC109 (both _make_request defs): `timeout` is the provider
    # API parameter passed straight to httpx (per-request httpx.Timeout), not
    # a wait bound this function owns — wrapping the body in asyncio.timeout()
    # would double-cap streaming-adjacent calls for no benefit.
    async def _make_request(
        self,
        method: str,
        path: str,
        request_body: dict[str, Any] = None,
        extra_headers: dict[str, str] = None,
        timeout: httpx.Timeout = None,  # noqa: ASYNC109
        files: dict[str, Any] = None,
        data: dict[str, Any] = None,
        request_id: str = "unknown"
    ) -> dict[str, Any]:
        """Unified non-streaming HTTP request to provider APIs.

        Holds a per-provider concurrency slot across the whole call. The retry
        loop in _make_request_inner runs inside the held slot, so retries
        reuse the same slot and it is released exactly once.
        HTTPStatusError: extracts error message from provider JSON response.
        RequestError: maps to a network error. extra_headers may add non-credential
        headers (e.g. Accept) but cannot overwrite Authorization — see INVARIANT
        above the class.
        """
        async with self.pool.acquire_slot(request_id):
            return await self._make_request_inner(
                method, path, request_body=request_body, extra_headers=extra_headers,
                timeout=timeout, files=files, data=data, request_id=request_id,
            )

    async def _make_request_inner(
        self,
        method: str,
        path: str,
        request_body: dict[str, Any] = None,
        extra_headers: dict[str, str] = None,
        timeout: httpx.Timeout = None,  # noqa: ASYNC109
        files: dict[str, Any] = None,
        data: dict[str, Any] = None,
        request_id: str = "unknown"
    ) -> dict[str, Any]:
        """Single HTTP attempt wrapped in the 429 backoff loop.

        Backoff formula: min(base_delay * 2^attempt, max_delay), bounds from
        settings. Rate-limit detection lives in _is_rate_limit_error. Only
        429-shaped errors are retried; everything else surfaces on the first
        attempt. See _make_request for the slot wrapper.
        """
        max_retries = self.settings.provider_max_retries
        for attempt in range(max_retries + 1):
            try:
                return await self._make_request_attempt(
                    method, path, request_body=request_body, extra_headers=extra_headers,
                    timeout=timeout, files=files, data=data, request_id=request_id,
                )
            except Exception as e:
                if _is_rate_limit_error(e) and attempt < max_retries:
                    delay = min(self.settings.provider_retry_base_delay * (2 ** attempt),
                                self.settings.provider_retry_max_delay)
                    logger.warning(
                        f"Rate limit exceeded, retrying in {delay}s (attempt {attempt + 1}/{max_retries})",
                        extra={
                            "delay_seconds": delay,
                            "attempt": attempt + 1,
                            "max_retries": max_retries,
                            "component": "base_provider"
                        })
                    await asyncio.sleep(delay)
                    continue
                raise
        raise RuntimeError("retry loop exhausted without an exception")

    async def _make_request_attempt(
        self,
        method: str,
        path: str,
        request_body: dict[str, Any] = None,
        extra_headers: dict[str, str] = None,
        timeout: httpx.Timeout = None,  # noqa: ASYNC109
        files: dict[str, Any] = None,
        data: dict[str, Any] = None,
        request_id: str = "unknown"
    ) -> dict[str, Any]:
        """One HTTP attempt: send, raise_for_status, parse the JSON response."""
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

                response = await self.pool.client.post(
                    f"{self.base_url}{path}",
                    headers=merged_headers,
                    json=request_body if not files else None,
                    files=files,
                    data=data,
                    timeout=timeout
                )
            elif method.upper() == "GET":
                response = await self.pool.client.get(
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
                             request_id=request_id, provider_name=self.provider_name) from e
        except httpx.HTTPStatusError as e:
            self._raise_provider_http_error(e, request_id)
        except httpx.RequestError as e:
            raise create_error(ErrorType.PROVIDER_NETWORK_ERROR, original_exception=e,
                             error_details=str(e), request_id=request_id, provider_name=self.provider_name) from e

    async def _stream_request(self, client: httpx.AsyncClient, url_path: str,
                              request_body: dict[str, Any], request_id: str = "unknown",
                              extra_headers: dict[str, str] = None) -> AsyncGenerator[bytes, None]:
        """Async generator streaming raw bytes from a provider API.

        Holds a per-provider concurrency slot across the ENTIRE iteration by the
        downstream consumer. `async with` releases on normal completion, on
        exception, and on generator close (AClose) — so a client disconnect also
        frees the slot. extra_headers are merged exactly like in _make_request.
        """
        async with self.pool.acquire_slot(request_id):
            async for chunk in self._stream_request_inner(client, url_path, request_body, request_id,
                                                          extra_headers):
                yield chunk

    async def _stream_request_inner(self, client: httpx.AsyncClient, url_path: str,
                              request_body: dict[str, Any], request_id: str = "unknown",
                              extra_headers: dict[str, str] = None) -> AsyncGenerator[bytes, None]:
        """Actual streaming implementation. See _stream_request for the slot wrapper.

        WHY: no retry loop here, unlike _make_request_inner — streaming is
        driven through open_provider_stream, which primes the first chunk
        BEFORE the response starts, so an upstream 429 already surfaces to the
        client as its real HTTP status instead of a 200 with an error frame;
        a retry loop at this layer would be unreachable for connection-time
        failures and would double-send a generation the client may already
        have partially received.
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

        stream_read_timeout = self.settings.stream_read_timeout
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
                         model_config: dict[str, Any], request_id: str = "unknown",
                         extra_headers: dict[str, str] = None) -> Any:
        raise NotImplementedError

    async def list_models(self, request_id: str = "unknown") -> dict[str, Any]:
        """Return the provider's model list (raw /models response)."""
        raise NotImplementedError

    async def transcriptions(self, request_body: dict[str, Any], provider_model_name: str,
                             model_config: dict[str, Any], request_id: str = "unknown",
                             extra_headers: dict[str, str] = None) -> Any:
        """Transcribe audio. request_body shape:

            {"audio": {"filename": str, "content_type": str, "data": bytes},
             "params": {"language"?, "temperature"?, "response_format"?,
                         "return_timestamps"?, "prompt"?}}
        """
        raise NotImplementedError
