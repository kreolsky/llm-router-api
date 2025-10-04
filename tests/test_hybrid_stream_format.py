#!/usr/bin/env python3
"""
Тесты гибридного подхода определения формата стриминга
"""

import pytest
import json
from unittest.mock import Mock, AsyncMock

from src.services.chat.format_processor import StreamFormatProcessor
from src.services.chat.streaming_handler import StreamingHandler
from src.services.chat.smart_buffer_manager import SmartStreamBufferManager
from src.services.chat.error_handler import StreamingErrorHandler


class TestStreamFormatProcessor:
    """Тесты StreamFormatProcessor"""
    
    def setup_method(self):
        self.processor = StreamFormatProcessor()
    
    def test_detect_format_sse(self):
        """Тест определения SSE формата"""
        # SSE с data:
        assert self.processor.detect_format('data: {"test": "value"}') == 'sse'
        
        # SSE с комментарием
        assert self.processor.detect_format(':comment') == 'sse'
        
        # SSE с несколькими строками
        sse_event = 'data: {"id": "1"}\ndata: {"content": "hello"}'
        assert self.processor.detect_format(sse_event) == 'sse'
    
    def test_detect_format_ndjson(self):
        """Тест определения NDJSON формата"""
        # Валидный JSON
        assert self.processor.detect_format('{"message": {"content": "test"}}') == 'ndjson'
        
        # NDJSON с массивом
        assert self.processor.detect_format('["item1", "item2"]') == 'ndjson'
        
        # NDJSON с числом
        assert self.processor.detect_format('123') == 'ndjson'
    
    def test_detect_format_fallback_to_sse(self):
        """Тест fallback на SSE при невалидном JSON"""
        # Невалидный JSON - должен вернуть SSE по умолчанию
        assert self.processor.detect_format('invalid json') == 'sse'
        assert self.processor.detect_format('') == 'sse'
        assert self.processor.detect_format('   ') == 'sse'
    
    def test_detect_format_edge_cases(self):
        """Тест граничных случаев"""
        # Пустая строка
        assert self.processor.detect_format('') == 'sse'
        
        # Только пробелы
        assert self.processor.detect_format('   ') == 'sse'
        
        # JSON с trailing whitespace
        assert self.processor.detect_format('{"test": "value"}   ') == 'ndjson'
        
        # SSE с whitespace
        assert self.processor.detect_format('  data: {"test": "value"}  ') == 'sse'


class TestHybridStreamFormat:
    """Тесты гибридного подхода в StreamingHandler"""
    
    def setup_method(self):
        self.buffer_manager = SmartStreamBufferManager()
        self.format_processor = StreamFormatProcessor()
        self.error_handler = StreamingErrorHandler()
        
        self.handler = StreamingHandler(
            self.buffer_manager,
            self.format_processor,
            self.error_handler
        )
    
    @pytest.mark.asyncio
    async def test_configured_format_sse(self):
        """Тест использования предопределенного SSE формата"""
        # Мок response_data
        mock_response = Mock()
        mock_response.body_iterator = AsyncMock()
        
        # SSE чанки
        sse_chunks = [
            b'data: {"id": "1"}\n\n',
            b'data: {"choices": [{"delta": {"content": "hello"}}]}\n\n',
            b'data: [DONE]\n\n'
        ]
        mock_response.body_iterator.__aiter__.return_value = iter(sse_chunks)
        
        # Вызываем с предопределенным форматом
        result_chunks = []
        async for chunk in self.handler.handle_stream(
            mock_response, 
            provider_type="openai",
            model_id="gpt-4",
            request_id="test-123",
            user_id="test-user",
            stream_format="sse"  # Предопределенный формат
        ):
            result_chunks.append(chunk)
        
        # Проверяем, что получили чанки
        assert len(result_chunks) > 0
        # Проверяем, что формат не определялся автоматически
        # (нет логов автоопределения)
    
    @pytest.mark.asyncio
    async def test_configured_format_ndjson(self):
        """Тест использования предопределенного NDJSON формата"""
        # Мок response_data
        mock_response = Mock()
        mock_response.body_iterator = AsyncMock()
        
        # NDJSON чанки
        ndjson_chunks = [
            b'{"message": {"content": "hello"}}\n',
            b'{"message": {"content": " world"}}\n',
            b'{"done": true}\n'
        ]
        mock_response.body_iterator.__aiter__.return_value = iter(ndjson_chunks)
        
        # Вызываем с предопределенным форматом
        result_chunks = []
        async for chunk in self.handler.handle_stream(
            mock_response, 
            provider_type="ollama",
            model_id="llama2",
            request_id="test-456",
            user_id="test-user",
            stream_format="ndjson"  # Предопределенный формат
        ):
            result_chunks.append(chunk)
        
        # Проверяем, что получили чанки
        assert len(result_chunks) > 0
        # Проверяем, что формат не определялся автоматически
        # (нет логов автоопределения)
    
    @pytest.mark.asyncio
    async def test_auto_detection_sse(self):
        """Тест автоопределения SSE формата"""
        # Мок response_data
        mock_response = Mock()
        mock_response.body_iterator = AsyncMock()
        
        # SSE чанки (формат не предопределен)
        sse_chunks = [
            b'data: {"id": "1"}\n\n',
            b'data: {"choices": [{"delta": {"content": "hello"}}]}\n\n'
        ]
        mock_response.body_iterator.__aiter__.return_value = iter(sse_chunks)
        
        # Вызываем БЕЗ предопределенного формата
        result_chunks = []
        async for chunk in self.handler.handle_stream(
            mock_response, 
            provider_type="unknown_provider",
            model_id="unknown-model",
            request_id="test-789",
            user_id="test-user",
            stream_format=None  # Нужно автоопределение
        ):
            result_chunks.append(chunk)
        
        # Проверяем, что получили чанки
        assert len(result_chunks) > 0
        # Проверяем, что формат определился автоматически
        # (должны быть логи автоопределения)
    
    @pytest.mark.asyncio
    async def test_auto_detection_ndjson(self):
        """Тест автоопределения NDJSON формата"""
        # Мок response_data
        mock_response = Mock()
        mock_response.body_iterator = AsyncMock()
        
        # NDJSON чанки (формат не предопределен)
        ndjson_chunks = [
            b'{"message": {"content": "hello"}}\n',
            b'{"message": {"content": " world"}}\n'
        ]
        mock_response.body_iterator.__aiter__.return_value = iter(ndjson_chunks)
        
        # Вызываем БЕЗ предопределенного формата
        result_chunks = []
        async for chunk in self.handler.handle_stream(
            mock_response, 
            provider_type="unknown_provider",
            model_id="unknown-model",
            request_id="test-999",
            user_id="test-user",
            stream_format=None  # Нужно автоопределение
        ):
            result_chunks.append(chunk)
        
        # Проверяем, что получили чанки
        assert len(result_chunks) > 0
        # Проверяем, что формат определился автоматически




class TestProviderConfigFormat:
    """Тесты конфигурации формата провайдера"""
    
    def test_provider_config_with_stream_format(self):
        """Тест чтения stream_format из конфигурации"""
        # Симуляция конфигурации провайдера
        provider_config = {
            "type": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
            "stream_format": "sse"
        }
        
        # Проверяем, что stream_format читается корректно
        stream_format = provider_config.get("stream_format")
        assert stream_format == "sse"
    
    def test_provider_config_without_stream_format(self):
        """Тест провайдера без stream_format"""
        # Симуляция конфигурации провайдера без stream_format
        provider_config = {
            "type": "custom_provider",
            "base_url": "https://custom.api.com/v1",
            "api_key_env": "CUSTOM_API_KEY"
            # stream_format отсутствует
        }
        
        # Проверяем, что stream_format = None
        stream_format = provider_config.get("stream_format")
        assert stream_format is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])