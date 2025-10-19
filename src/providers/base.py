import httpx
import os
import json # Import json for parsing error responses
import asyncio
import time
from typing import Dict, Any, AsyncGenerator, Callable
from functools import wraps
from fastapi.responses import StreamingResponse, JSONResponse

from ..utils.deep_merge import deep_merge
from ..core.error_handling import ErrorHandler, ErrorType, ErrorContext # Import error handling
from ..core.logging import logger


def retry_on_rate_limit(max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 30.0):
    """
    Декоратор для повторных попыток при ошибках 429 (Too Many Requests)
    
    Args:
        max_retries: Максимальное количество повторных попыток
        base_delay: Базовая задержка между попытками (секунды)
        max_delay: Максимальная задержка (секунды)
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
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
                    
                    if is_rate_limit and attempt < max_retries:
                        # Экспоненциальное увеличение задержки
                        delay = min(base_delay * (2 ** attempt), max_delay)
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
                        
                        logger.warning(f"Rate limit exceeded, retrying in {delay}s (attempt {attempt + 1}/{max_retries})", extra={
                            "delay_seconds": delay,
                            "attempt": attempt + 1,
                            "max_retries": max_retries,
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
    def __init__(self, config: Dict[str, Any], client: httpx.AsyncClient):
        self.base_url = config.get("base_url")
        self.api_key_env = config.get("api_key_env")
        self.headers = config.get("headers", {})
        self.api_key = os.environ.get(self.api_key_env) if self.api_key_env else None
        self.client = client # Store the httpx client

        if not self.base_url:
            context = ErrorContext(provider_name=self.__class__.__name__.replace("Provider", "").lower())
            raise ErrorHandler.handle_provider_config_error(
                error_details="Provider base_url is not configured.",
                context=context
            )
        
        # Only set API key and Authorization header if api_key_env is provided
        if self.api_key_env:
            if not self.api_key:
                context = ErrorContext(provider_name=self.__class__.__name__.replace("Provider", "").lower())
                raise ErrorHandler.handle_provider_config_error(
                    error_details=f"API key for {self.api_key_env} is not set in environment variables.",
                    context=context
                )
            self.headers["Authorization"] = f"Bearer {self.api_key}"

    @retry_on_rate_limit(max_retries=3, base_delay=1.0, max_delay=30.0)
    async def _stream_request(self, client: httpx.AsyncClient, url_path: str, request_body: Dict[str, Any]) -> StreamingResponse:
        """Stream request with optimized timeouts for streaming"""
        # Create error context for this request
        context = ErrorContext(
            request_id=request_body.get("request_id", "unknown"),
            provider_name=self.__class__.__name__.replace("Provider", "").lower()
        )
        
        # DEBUG логирование запроса к провайдеру
        logger.debug_data(
            title="Base Provider Request",
            data={
                "url": f"{self.base_url}{url_path}",
                "headers": self.headers,
                "request_body": request_body,
                "component": "base_provider"
            },
            request_id=request_body.get("request_id", "unknown"),
            component="base_provider",
            data_flow="to_provider"
        )
        
        # Optimized timeout for streaming:
        # - connect: 10s to establish connection
        # - read: 30s between chunks (if no chunk in 30s, timeout)
        # - write: 10s to send request
        # - pool: 10s to get connection from pool
        stream_timeout = httpx.Timeout(
            connect=10.0,
            read=30.0,    # Time between chunks, not total time
            write=10.0,
            pool=10.0
        )
        
        async def generate():
            async with client.stream("POST", f"{self.base_url}{url_path}",
                                     headers=self.headers,
                                     json=request_body,
                                     timeout=stream_timeout) as response:
              
              # DEBUG логирование заголовков ответа
              logger.debug_data(
                  title="Provider Response Headers",
                  data={
                      "status_code": response.status_code,
                      "headers": dict(response.headers)
                  },
                  request_id=request_body.get("request_id", "unknown"),
                  component="base_provider",
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
              
              async for chunk in response.aiter_bytes():
                  yield chunk
        return StreamingResponse(generate(), media_type="text/event-stream")

    async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        raise NotImplementedError

    async def embeddings(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        raise NotImplementedError

    async def transcriptions(self, audio_file: Any, request_params: Dict[str, Any], model_config: Dict[str, Any]) -> Any:
        raise NotImplementedError
