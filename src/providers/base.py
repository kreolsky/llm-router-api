"""Base provider with shared HTTP, streaming, retry, and error handling logic."""
import httpx
import os
import json
import asyncio
import time
from typing import Dict, Any, AsyncGenerator, Callable, Optional
from functools import wraps
from fastapi.responses import JSONResponse

from ..utils.deep_merge import deep_merge
from ..core.error_handling import ErrorHandler, ErrorType, ErrorContext
from ..core.error_handling.error_logger import ErrorLogger
from ..core.logging import logger


def retry_on_rate_limit(max_retries: Optional[int] = None, base_delay: Optional[float] = None, max_delay: Optional[float] = None, config_manager=None):
    """Retry decorator for 429 (Too Many Requests) with exponential backoff.

    Backoff formula: min(base_delay * 2^attempt, max_delay).
    Rate-limit detection checks both e.status_code == 429 and
    e.original_exception.response.status_code == 429 (wrapped httpx errors).
    Config resolution: self.config_manager > closure arg > hardcoded defaults.
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Get retry settings from config_manager if available, otherwise use defaults
            # Try to get config_manager from the first argument (self)
            cm = None
            if args and hasattr(args[0], 'config_manager'):
                cm = args[0].config_manager
            elif config_manager:
                cm = config_manager

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
                    if hasattr(e, 'status_code') and e.status_code == 429:
                        is_rate_limit = True
                    # Check for original exception with 429 status
                    elif hasattr(e, 'original_exception') and hasattr(e.original_exception, 'response') and e.original_exception.response.status_code == 429:
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
            raise last_exception
        return wrapper
    return decorator

class BaseProvider:
    def __init__(self, config: Dict[str, Any], client: httpx.AsyncClient, config_manager=None):
        """Initialize provider from config dict.

        Reads API key from the env var named by config['api_key_env'].
        Stores the shared httpx.AsyncClient (lifecycle managed in main.py lifespan).
        Auto-derives provider_name from class name for logging.
        Sets default Content-Type: application/json (subclasses may override before super().__init__).

        Raises:
            HTTPException: If base_url is missing or the env var for the API key is unset.
        """
        self.base_url = config.get("base_url")
        self.api_key_env = config.get("api_key_env")
        self.headers = config.get("headers", {})
        self.api_key = os.environ.get(self.api_key_env) if self.api_key_env else None
        self.client = client
        self.config_manager = config_manager
        self.provider_name = self.__class__.__name__.replace("Provider", "").lower()
        self.headers.setdefault("Content-Type", "application/json")

        if not self.base_url:
            context = ErrorContext(provider_name=self.provider_name)
            raise ErrorHandler.handle_provider_config_error(
                error_details="Provider base_url is not configured.",
                context=context
            )
        
        # Only set API key and Authorization header if api_key_env is provided
        if self.api_key_env:
            if not self.api_key:
                context = ErrorContext(provider_name=self.provider_name)
                raise ErrorHandler.handle_provider_config_error(
                    error_details=f"API key for {self.api_key_env} is not set in environment variables.",
                    context=context
                )
            self.headers["Authorization"] = f"Bearer {self.api_key}"

    def _log_provider_data(self, title: str, data: Dict[str, Any], request_id: str, data_flow: str, component: str = None) -> None:
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

    def _apply_model_config(self, request_body: Dict[str, Any], provider_model_name: str,
                            model_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Set provider model name and merge model-level options into request body.
        """
        request_body["model"] = provider_model_name
        if options := model_config.get("options"):
            request_body = deep_merge(request_body, options)
        return request_body

    def _raise_provider_http_error(self, e: httpx.HTTPStatusError, context: ErrorContext) -> None:
        """Extract error message from provider response and raise HTTPException.

        Handles ResponseNotRead (streaming context where body isn't buffered).
        Logs via ErrorLogger before raising.
        """
        from fastapi import HTTPException

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

        ErrorLogger.log_provider_error(
            provider_name=self.provider_name,
            error_details=response_text,
            status_code=e.response.status_code,
            context=context,
            original_exception=e
        )

        raise HTTPException(
            status_code=e.response.status_code,
            detail={
                "error": {
                    "code": e.response.status_code,
                    "message": error_message,
                    "metadata": {
                        "provider_name": self.provider_name,
                        "raw": response_text
                    }
                }
            }
        ) from e

    def _get_timeout(self, timeout_type: str, default_value: float) -> float:
        """Read a named timeout from config_manager, falling back to default_value."""
        if self.config_manager and hasattr(self.config_manager, timeout_type):
            return getattr(self.config_manager, timeout_type)
        return default_value

    @retry_on_rate_limit(config_manager=None)  # Will be set by self.config_manager in the wrapper
    async def _make_request(
        self,
        method: str,
        path: str,
        request_body: Dict[str, Any] = None,
        headers: Dict[str, str] = None,
        timeout: httpx.Timeout = None,
        files: Dict[str, Any] = None,
        data: Dict[str, Any] = None,
        request_id: str = "unknown",
        base_url: str = None
    ) -> Dict[str, Any]:
        """Unified non-streaming HTTP request to provider APIs.

        Decorated with @retry_on_rate_limit, so 429 responses are retried automatically.
        HTTPStatusError: extracts error message from provider JSON response.
        RequestError: maps to a network error. base_url param allows per-request
        override (used by transcription service).
        """
        effective_base_url = base_url or self.base_url

        context = ErrorContext(
            request_id=request_id,
            provider_name=self.provider_name
        )

        merged_headers = {**self.headers}
        if headers:
            merged_headers.update(headers)

        self._log_provider_data(
            title=f"{self.__class__.__name__} Request",
            data={
                "url": f"{effective_base_url}{path}",
                "headers": merged_headers,
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
                    f"{effective_base_url}{path}",
                    headers=merged_headers,
                    json=request_body if not files else None,
                    files=files,
                    data=data,
                    timeout=timeout
                )
            elif method.upper() == "GET":
                response = await self.client.get(
                    f"{effective_base_url}{path}",
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
            
        except httpx.HTTPStatusError as e:
            self._raise_provider_http_error(e, context)
        except httpx.RequestError as e:
            raise ErrorHandler.handle_provider_network_error(e, context, self.provider_name)

    async def _stream_request(self, client: httpx.AsyncClient, url_path: str, request_body: Dict[str, Any]) -> AsyncGenerator[bytes, None]:
        """Async generator streaming raw bytes from a provider API.

        Uses client.stream() context manager for memory-efficient chunk iteration.
        Error hierarchy inside stream context:
        - HTTPStatusError with ResponseNotRead fallback for error body
        - PoolTimeout → 503 (connection pool exhausted)
        - RequestError → generic network error
        """
        request_id = request_body.get("request_id", "unknown")
        context = ErrorContext(
            request_id=request_id,
            provider_name=self.provider_name
        )

        self._log_provider_data(
            title="Base Provider Request",
            data={
                "url": f"{self.base_url}{url_path}",
                "headers": self.headers,
                "request_body": request_body
            },
            request_id=request_id,
            data_flow="to_provider"
        )

        stream_timeout = self._create_timeout()

        logger.debug(f"Starting stream request to {url_path}", extra={
            "url": f"{self.base_url}{url_path}",
            "timeout": str(stream_timeout),
            "request_id": request_id
        })
        start_time = time.time()
        try:
            async with client.stream("POST", f"{self.base_url}{url_path}",
                                     headers=self.headers,
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
                    self._raise_provider_http_error(e, context)
                # WHY: PoolTimeout means all connections in use, not a network failure — maps to 503
                except httpx.PoolTimeout as e:
                    http_exception = ErrorHandler.handle_service_unavailable(
                        error_details="Connection pool exhausted. Please retry later.",
                        context=context,
                        original_exception=e
                    )
                    raise http_exception from e
                except httpx.RequestError as e:
                    http_exception = ErrorHandler.handle_provider_network_error(
                        original_exception=e,
                        context=context
                    )
                    raise http_exception from e

                logger.debug(f"Starting to iterate over stream chunks for {request_id}")
                async for chunk in response.aiter_bytes():
                    logger.debug(f"Provider yielded {len(chunk)} bytes", extra={
                        "request_id": request_id,
                        "chunk_size": len(chunk)
                    })
                    yield chunk
                logger.debug(f"Provider stream finished for {request_id}")
        except Exception as e:
            logger.error(f"Stream request failed after {time.time() - start_time:.2f}s: {str(e)}", extra={
                "error_type": type(e).__name__,
                "request_id": request_id
            }, exc_info=True)
            raise

    async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        raise NotImplementedError

    async def embeddings(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        raise NotImplementedError

    async def transcriptions(self, audio_file: Any, request_params: Dict[str, Any], model_config: Dict[str, Any]) -> Any:
        raise NotImplementedError
