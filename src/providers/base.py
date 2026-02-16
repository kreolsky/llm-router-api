import httpx
import os
import json # Import json for parsing error responses
import asyncio
import time
from typing import Dict, Any, AsyncGenerator, Callable, Optional
from functools import wraps
from fastapi.responses import StreamingResponse, JSONResponse

from ..utils.deep_merge import deep_merge
from ..core.error_handling import ErrorHandler, ErrorType, ErrorContext # Import error handling
from ..core.logging import logger


def retry_on_rate_limit(max_retries: Optional[int] = None, base_delay: Optional[float] = None, max_delay: Optional[float] = None, config_manager=None):
    """
    Декоратор для повторных попыток при ошибках 429 (Too Many Requests)

    Args:
        max_retries: Максимальное количество повторных попыток (optional, uses config_manager if not provided)
        base_delay: Базовая задержка между попытками (секунды) (optional, uses config_manager if not provided)
        max_delay: Максимальная задержка (секунды) (optional, uses config_manager if not provided)
        config_manager: ConfigManager instance to get retry settings from
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
                        # Экспоненциальное увеличение задержки
                        delay = min(actual_base_delay * (2 ** attempt), actual_max_delay)
                        last_exception = e
                        
                        # Извлекаем время ожидания из заголовка Retry-After, если есть
                        retry_after = None
                        if hasattr(e, 'original_exception') and hasattr(e.original_exception, 'response'):
                            retry_after = e.original_exception.response
                        elif hasattr(e, 'response'):
                            retry_after = e.response
                            
                        if retry_after and retry_after.headers:
                            retry_after_header = retry_after.headers.get('Retry-After')
                            if retry_after_header:
                                try:
                                    delay = float(retry_after_header)
                                except ValueError:
                                    # Если не число, пробуем разобрать как HTTP-дату
                                    pass
                        
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
        self.base_url = config.get("base_url")
        self.api_key_env = config.get("api_key_env")
        self.headers = config.get("headers", {})
        self.api_key = os.environ.get(self.api_key_env) if self.api_key_env else None
        self.client = client # Store the httpx client
        self.config_manager = config_manager # Store config_manager for retry settings
        # Automatically set provider name from class name for logging
        self.provider_name = self.__class__.__name__.replace("Provider", "").lower()

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
        """
        Standardized logging method for provider requests and responses.
        
        This method provides a consistent way to log provider data across all providers,
        ensuring uniform debug information for troubleshooting.
        
        Args:
            title: Descriptive title for the log entry (e.g., "OpenAI Request", "Anthropic Response")
            data: Dictionary containing the data to log (request body, response, headers, etc.)
            request_id: Unique identifier for the request
            data_flow: Direction of data flow ("to_provider" or "from_provider")
            component: Component name for logging (defaults to provider_name if not specified)
        
        Example:
            self._log_provider_data(
                title="Provider Request",
                data={"url": url, "headers": headers, "request_body": body},
                request_id="req-123",
                data_flow="to_provider"
            )
        """
        if component is None:
            component = f"{self.provider_name}_provider"
        
        logger.debug_data(
            title=title,
            data=data,
            request_id=request_id,
            component=component,
            data_flow=data_flow
        )

    def _get_timeout(self, timeout_type: str, default_value: float) -> float:
        """
        Get timeout value from config_manager or use default.
        
        This method standardizes timeout configuration across all providers,
        allowing provider-specific timeouts while providing sensible defaults.
        
        Args:
            timeout_type: Type of timeout (e.g., "openai_connect_timeout", "anthropic_timeout")
            default_value: Default timeout value to use if config_manager is not available
        
        Returns:
            Timeout value in seconds
        
        Example:
            connect_timeout = self._get_timeout("openai_connect_timeout", 60.0)
        """
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
        request_id: str = "unknown"
    ) -> Dict[str, Any]:
        """
        Unified method for non-streaming HTTP requests to provider APIs.
        
        This method centralizes HTTP request logic, logging, error handling, and timeout management
        across all providers, reducing code duplication and ensuring consistent behavior.
        
        Args:
            method: HTTP method ("GET", "POST", etc.)
            path: API endpoint path (relative to base_url)
            request_body: JSON body for the request (for POST requests)
            headers: Additional headers to merge with default headers
            timeout: Custom timeout configuration (uses default if not specified)
            files: Files to upload (for multipart/form-data requests)
            data: Form data for multipart requests
            request_id: Unique identifier for the request (for logging)
        
        Returns:
            JSON response from the provider
        
        Raises:
            HTTPException: Wrapped httpx exceptions with proper error context
        
        Example:
            response = await self._make_request(
                method="POST",
                path="/chat/completions",
                request_body={"model": "gpt-4", "messages": [...]},
                request_id="req-123"
            )
        """
        # Create error context for this request
        context = ErrorContext(
            request_id=request_id,
            provider_name=self.provider_name
        )
        
        # Merge headers if provided
        merged_headers = {**self.headers}
        if headers:
            merged_headers.update(headers)
        
        # Log the outgoing request
        self._log_provider_data(
            title=f"{self.__class__.__name__} Request",
            data={
                "url": f"{self.base_url}{path}",
                "headers": merged_headers,
                "request_body": request_body,
                "has_files": files is not None,
                "has_data": data is not None
            },
            request_id=request_id,
            data_flow="to_provider"
        )
        
        try:
            # Execute the HTTP request
            if method.upper() == "POST":
                response = await self.client.post(
                    f"{self.base_url}{path}",
                    headers=merged_headers,
                    json=request_body,
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
            
            # Raise exception for HTTP errors
            response.raise_for_status()
            
            # Parse and return JSON response
            response_json = response.json()
            
            # Log the incoming response
            self._log_provider_data(
                title=f"{self.__class__.__name__} Response",
                data=response_json,
                request_id=request_id,
                data_flow="from_provider"
            )
            
            return response_json
            
        except httpx.HTTPStatusError as e:
            # Handle HTTP errors with proper context
            raise ErrorHandler.handle_provider_http_error(e, context, self.provider_name)
        except httpx.RequestError as e:
            # Handle network errors with proper context
            raise ErrorHandler.handle_provider_network_error(e, context, self.provider_name)

    @retry_on_rate_limit(config_manager=None)  # Will be set by self.config_manager in the wrapper
    async def _stream_request(self, client: httpx.AsyncClient, url_path: str, request_body: Dict[str, Any]) -> StreamingResponse:
        """
        Stream request with optimized timeouts for streaming.
        
        This method handles streaming requests to provider APIs, with proper timeout configuration
        and error handling. It uses the unified logging infrastructure for consistency.
        
        Args:
            client: httpx.AsyncClient instance to use for the request
            url_path: API endpoint path (relative to base_url)
            request_body: Request body containing parameters and request_id
        
        Returns:
            StreamingResponse with SSE (Server-Sent Events) content
        
        Raises:
            HTTPException: Wrapped httpx exceptions with proper error context
        """
        # Create error context for this request
        request_id = request_body.get("request_id", "unknown")
        context = ErrorContext(
            request_id=request_id,
            provider_name=self.provider_name
        )
        
        # DEBUG логирование запроса к провайдеру
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
        
        # Optimized timeout for streaming:
        # - connect: 60s to establish connection
        # - read: None (disable read timeout for streaming)
        # - write: None (disable write timeout to allow large images)
        # - pool: Use client's pool timeout
        stream_timeout = httpx.Timeout(
            connect=client.timeout.connect,
            read=None,    # Disable read timeout for streaming
            write=None,   # Disable write timeout to allow large images
            pool=client.timeout.pool
        )
        
        # Reuse the existing client instead of creating a new one
        async def generate():
            logger.debug(f"Starting stream request to {url_path}", extra={
                "url": f"{self.base_url}{url_path}",
                "timeout": str(stream_timeout),
                "request_id": request_body.get("request_id", "unknown")
            })
            start_time = time.time()
            try:
                async with client.stream("POST", f"{self.base_url}{url_path}",
                                         headers=self.headers,
                                         json=request_body,
                                         timeout=stream_timeout) as response:
                    logger.debug(f"Stream response headers received after {time.time() - start_time:.2f}s", extra={
                        "status_code": response.status_code,
                        "request_id": request_body.get("request_id", "unknown")
                    })
              
                    # DEBUG логирование заголовков ответа
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
                        # Сначала читаем ответ, чтобы избежать ResponseNotRead
                        response_text = ""
                        try:
                            # Для стриминговых ответов нужно сначала прочитать контент
                            response_text = e.response.text
                        except httpx.ResponseNotRead:
                            # Если ответ не может быть прочитан, используем общее сообщение
                            response_text = "Unable to read error response from provider"
                        
                        # Специальная обработка для ошибки 429
                        error_code = "provider_api_error"
                        if e.response.status_code == 429:
                            error_message = "Provider rate limit exceeded (429 Too Many Requests). Please retry after a delay."
                            error_code = "rate_limit_exceeded"
                        else:
                            error_message = f"Provider API error: {e.response.status_code} - {response_text}"
                        
                        # Пытаемся распарсить JSON из ответа
                        try:
                            error_json = e.response.json()
                            if "error" in error_json and "message" in error_json["error"]:
                                error_message = error_json["error"]["message"]
                                if "code" in error_json["error"]:
                                    error_code = error_json["error"]["code"]
                            elif "message" in error_json:
                                error_message = error_json["message"]
                        except (json.JSONDecodeError, httpx.ResponseNotRead):
                            pass # Если не JSON или ответ не прочитан, используем error_message по умолчанию
                        
                        # Use ErrorHandler to create and raise the appropriate exception
                        http_exception = ErrorHandler.handle_provider_stream_error(
                            error_details=error_message,
                            context=context,
                            status_code=e.response.status_code,
                            error_code=error_code,
                            original_exception=e
                        )
                        raise http_exception from e
                    except httpx.RequestError as e:
                        # Use ErrorHandler to create and raise the appropriate exception
                        http_exception = ErrorHandler.handle_provider_network_error(
                            original_exception=e,
                            context=context
                        )
                        raise http_exception from e
                    except httpx.PoolTimeout as e:
                        # Handle connection pool exhaustion gracefully
                        http_exception = ErrorHandler.handle_service_unavailable(
                            error_details="Connection pool exhausted. Please retry later.",
                            context=context,
                            original_exception=e
                        )
                        raise http_exception from e
                    
                    logger.debug(f"Starting to iterate over stream chunks for {request_body.get('request_id', 'unknown')}")
                    async for chunk in response.aiter_bytes():
                        logger.debug(f"Provider yielded {len(chunk)} bytes", extra={
                            "request_id": request_body.get("request_id", "unknown"),
                            "chunk_size": len(chunk)
                        })
                        yield chunk
                    logger.debug(f"Provider stream finished for {request_body.get('request_id', 'unknown')}")
            except Exception as e:
                logger.error(f"Stream request failed after {time.time() - start_time:.2f}s: {str(e)}", extra={
                    "error_type": type(e).__name__,
                    "request_id": request_body.get("request_id", "unknown")
                })
                raise

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
        )

    async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        raise NotImplementedError

    async def embeddings(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        raise NotImplementedError

    async def transcriptions(self, audio_file: Any, request_params: Dict[str, Any], model_config: Dict[str, Any]) -> Any:
        raise NotImplementedError
