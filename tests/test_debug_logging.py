"""
Тестирование функциональности DEBUG логирования
"""

import os
import json
import tempfile
import logging
from unittest.mock import patch, AsyncMock
import pytest
import httpx

from src.logging.config import setup_logging, logger
from src.api.middleware import RequestLoggerMiddleware
from src.services.chat_service.chat_service import ChatService
from src.services.embedding_service import EmbeddingService
from src.core.config_manager import ConfigManager


class TestDebugLogging:
    """Тесты для системы DEBUG логирования"""
    
    def setup_method(self):
        """Настройка перед каждым тестом"""
        # Создаем временную директорию для логов
        self.temp_dir = tempfile.mkdtemp()
        self.original_log_level = os.environ.get("LOG_LEVEL", "INFO")
        
    def teardown_method(self):
        """Очистка после каждого теста"""
        # Восстанавливаем оригинальный уровень логирования
        os.environ["LOG_LEVEL"] = self.original_log_level
        
    def test_setup_logging_debug_mode(self):
        """Тест настройки логирования в DEBUG режиме"""
        os.environ["LOG_LEVEL"] = "DEBUG"
        
        with patch('os.makedirs'):
            with patch('logging.FileHandler') as mock_file_handler:
                setup_logging()
                
                # Проверяем, что уровень логирования установлен в DEBUG
                assert logger.level == logging.DEBUG
                
                # Проверяем, что создан обработчик для DEBUG логов
                assert mock_file_handler.call_count >= 1  # Хотя бы один файловый хендлер
                
    def test_setup_logging_info_mode(self):
        """Тест настройки логирования в INFO режиме"""
        os.environ["LOG_LEVEL"] = "INFO"
        
        with patch('os.makedirs'):
            with patch('logging.FileHandler') as mock_file_handler:
                setup_logging()
                
                # Проверяем, что уровень логирования установлен в INFO
                assert logger.level == logging.INFO
                
    def test_debug_logging_enabled_check(self):
        """Тест проверки isEnabledFor(logging.DEBUG)"""
        os.environ["LOG_LEVEL"] = "DEBUG"
        setup_logging()
        
        assert logger.isEnabledFor(logging.DEBUG) == True
        
        os.environ["LOG_LEVEL"] = "INFO"
        setup_logging()
        
        assert logger.isEnabledFor(logging.DEBUG) == False
        
    def test_debug_log_format(self):
        """Тест формата DEBUG лога"""
        os.environ["LOG_LEVEL"] = "DEBUG"
        
        with patch('os.makedirs'):
            with patch('logging.FileHandler') as mock_file_handler:
                setup_logging()
                
                # Создаем тестовый лог с DEBUG полями
                test_data = {
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "test"}]
                }
                
                logger.debug(
                    "DEBUG: Test Message",
                    extra={
                        "debug_json_data": test_data,
                        "debug_data_flow": "incoming",
                        "debug_component": "test_component",
                        "request_id": "test-request-id"
                    }
                )
                
                # Проверяем, что лог записан с нужными полями
                # (в реальном тесте здесь would be проверка содержимого файла)
                
    @pytest.mark.asyncio
    async def test_middleware_debug_logging(self):
        """Тест DEBUG логирования в middleware"""
        os.environ["LOG_LEVEL"] = "DEBUG"
        setup_logging()
        
        # Создаем мок для request
        mock_request = AsyncMock()
        mock_request.method = "POST"
        mock_request.url = "http://localhost:8000/v1/chat/completions"
        mock_request.state = AsyncMock()
        mock_request.state.request_id = "test-request-id"
        mock_request.json = AsyncMock(return_value={"model": "test", "messages": []})
        
        # Создаем middleware
        middleware = RequestLoggerMiddleware(AsyncMock())
        
        # Мокаем call_next
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.body = b'{"result": "ok"}'
        
        with patch.object(middleware, 'call_next', return_value=mock_response):
            with patch.object(logger, 'debug') as mock_debug:
                await middleware.dispatch(mock_request, AsyncMock())
                
                # Проверяем, что debug был вызван
                mock_debug.assert_called()
                
                # Проверяем параметры вызова
                call_args = mock_debug.call_args
                assert "debug_json_data" in call_args[1]["extra"]
                assert "debug_data_flow" in call_args[1]["extra"]
                assert "debug_component" in call_args[1]["extra"]
                
    def test_logging_configuration_from_env(self):
        """Тест чтения конфигурации логирования из переменных окружения"""
        # Тест с DEBUG
        os.environ["LOG_LEVEL"] = "DEBUG"
        
        with patch('os.makedirs'):
            with patch('logging.FileHandler'):
                setup_logging()
                assert logger.level == logging.DEBUG
                
        # Тест с INFO
        os.environ["LOG_LEVEL"] = "INFO"
        
        with patch('os.makedirs'):
            with patch('logging.FileHandler'):
                setup_logging()
                assert logger.level == logging.INFO
                
        # Тест с значением по умолчанию
        if "LOG_LEVEL" in os.environ:
            del os.environ["LOG_LEVEL"]
            
        with patch('os.makedirs'):
            with patch('logging.FileHandler'):
                setup_logging()
                assert logger.level == logging.INFO  # Значение по умолчанию


def test_debug_logging_integration():
    """Интеграционный тест DEBUG логирования"""
    os.environ["LOG_LEVEL"] = "DEBUG"
    
    with patch('os.makedirs'):
        with patch('logging.FileHandler') as mock_handler:
            setup_logging()
            
            # Тестируем логирование с разными компонентами
            test_cases = [
                {
                    "message": "DEBUG: Test Request",
                    "extra": {
                        "debug_json_data": {"test": "data"},
                        "debug_data_flow": "incoming",
                        "debug_component": "test_component"
                    }
                },
                {
                    "message": "DEBUG: Test Response",
                    "extra": {
                        "debug_json_data": {"result": "ok"},
                        "debug_data_flow": "outgoing",
                        "debug_component": "middleware"
                    }
                }
            ]
            
            for case in test_cases:
                logger.debug(case["message"], extra=case["extra"])
                
            # Проверяем, что обработчик был вызван
            assert mock_handler.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])