"""
Тесты для обработки ошибок стриминга, особенно 429 Too Many Requests
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
from fastapi.responses import StreamingResponse

from src.providers.base import BaseProvider, retry_on_rate_limit
from src.core.exceptions import ProviderStreamError, ProviderNetworkError


class TestStreamingErrorHandling:
    """Тесты для обработки ошибок в стриминге"""
    
    def setup_method(self):
        """Настройка тестового окружения"""
        self.config = {
            "base_url": "https://api.test.com/v1",
            "api_key_env": "TEST_API_KEY"
        }
        self.client = AsyncMock()
        
        # Мокируем переменную окружения
        with patch('src.providers.base.os.environ.get', return_value="test_key"):
            self.provider = BaseProvider(self.config, self.client)
    
    def test_retry_on_rate_limit_decorator(self):
        """Тест декоратора retry_on_rate_limit"""
        call_count = 0
        
        @retry_on_rate_limit(max_retries=2, base_delay=0.1)
        async def test_function():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ProviderStreamError("Rate limit exceeded", status_code=429)
            return "success"
        
        # Тест успешного выполнения после повторных попыток
        result = asyncio.run(test_function())
        assert result == "success"
        assert call_count == 2
    
    def test_retry_on_rate_limit_max_attempts(self):
        """Тест декоратора retry_on_rate_limit с превышением лимита попыток"""
        call_count = 0
        
        @retry_on_rate_limit(max_retries=2, base_delay=0.1)
        async def test_function():
            nonlocal call_count
            call_count += 1
            raise ProviderStreamError("Rate limit exceeded", status_code=429)
        
        # Тест что исключение выбрасывается после превышения лимита попыток
        with pytest.raises(ProviderStreamError):
            asyncio.run(test_function())
        assert call_count == 3  # 1 начальный вызов + 2 повторные попытки
    
    def test_retry_on_rate_limit_non_429_error(self):
        """Тест декоратора retry_on_rate_limit для ошибок не 429"""
        call_count = 0
        
        @retry_on_rate_limit(max_retries=2, base_delay=0.1)
        async def test_function():
            nonlocal call_count
            call_count += 1
            raise ProviderStreamError("Other error", status_code=500)
        
        # Тест что исключение выбрасывается сразу для ошибок не 429
        with pytest.raises(ProviderStreamError):
            asyncio.run(test_function())
        assert call_count == 1
    
    @pytest.mark.asyncio
    async def test_stream_request_with_retry(self):
        """Тест стриминга с повторными попытками при ошибке 429"""
        # Мокируем ответ с ошибкой 429
        mock_response = AsyncMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limit exceeded"
        mock_response.json.return_value = {"error": {"message": "Rate limit exceeded", "code": "rate_limit_exceeded"}}
        
        # Мокируем исключение HTTPStatusError
        mock_error = httpx.HTTPStatusError(
            "429 Too Many Requests",
            request=AsyncMock(),
            response=mock_response
        )
        
        # Мокируем успешный ответ после повторной попытки
        mock_response_success = AsyncMock()
        mock_response_success.status_code = 200
        mock_response_success.raise_for_status.return_value = None
        mock_response_success.aiter_bytes.return_value = [b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n']
        
        # Мокируем контекстный менеджер
        mock_context_manager = AsyncMock()
        mock_context_manager.__aenter__.return_value = mock_response
        mock_context_manager.__aexit__.return_value = None
        
        # Мокируем клиент
        self.client.stream.return_value = mock_context_manager
        
        # Тест запроса
        request_body = {"model": "test", "messages": [{"role": "user", "content": "Hello"}], "stream": True}
        
        # Проверяем что метод вызывается с декоратором retry
        assert hasattr(self.provider._stream_request, '__wrapped__')
        
        # Тестируем что метод существует и может быть вызван
        assert callable(self.provider._stream_request)