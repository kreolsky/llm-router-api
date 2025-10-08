#!/usr/bin/env python3
"""
Тест для проверки исправления проблемы с "съеданием" первого токена в стриминге
"""

import os
import sys
import logging
import tempfile
import json
from unittest.mock import AsyncMock, MagicMock, patch

# Добавляем src в путь
sys.path.append('src')

from src.logging.config import setup_logging, logger
from src.services.chat_service.chat_service import ChatService
from src.core.config_manager import ConfigManager
from fastapi import Request
from fastapi.responses import StreamingResponse


async def test_streaming_fix():
    """Тестирование исправления проблемы стриминга"""
    print("=== Тестирование исправления проблемы стриминга ===")
    
    # Включаем DEBUG логирование
    os.environ["LOG_LEVEL"] = "DEBUG"
    setup_logging()
    
    print(f"Logger level: {logger.level}")
    print(f"DEBUG enabled: {logger.isEnabledFor(logging.DEBUG)}")
    
    # Создаем моки для зависимостей
    mock_config_manager = MagicMock()
    mock_config_manager.get_config.return_value = {
        "models": {
            "test-model": {
                "provider": "openai",
                "provider_model_name": "gpt-4"
            }
        },
        "providers": {
            "openai": {
                "type": "openai",
                "base_url": "https://api.openai.com/v1"
            }
        }
    }
    
    mock_httpx_client = MagicMock()
    mock_model_service = MagicMock()
    
    # Создаем экземпляр ChatService
    chat_service = ChatService(mock_config_manager, mock_httpx_client, mock_model_service)
    
    # Создаем мок для запроса
    mock_request = MagicMock(spec=Request)
    mock_request.state = MagicMock()
    mock_request.state.request_id = "test-request-123"
    mock_request.json = AsyncMock(return_value={
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True
    })
    
    # Создаем мок для StreamingResponse
    mock_streaming_response = MagicMock(spec=StreamingResponse)
    mock_streaming_response.body_iterator = AsyncMock()
    
    # Создаем тестовые chunks
    test_chunks = [
        b'data: {"id": "test", "choices": [{"delta": {"content": "H"}}]}\n\n',
        b'data: {"id": "test", "choices": [{"delta": {"content": "e"}}]}\n\n',
        b'data: {"id": "test", "choices": [{"delta": {"content": "l"}}]}\n\n',
        b'data: {"id": "test", "choices": [{"delta": {"content": "l"}}]}\n\n',
        b'data: {"id": "test", "choices": [{"delta": {"content": "o"}}]}\n\n',
        b'data: [DONE]\n\n'
    ]
    
    # Настраиваем итератор chunks
    async def mock_chunk_iterator():
        for chunk in test_chunks:
            yield chunk
    
    mock_streaming_response.body_iterator.__aiter__ = mock_chunk_iterator().__aiter__
    mock_streaming_response.media_type = "text/event-stream"
    
    # Мокаем провайдер
    with patch('src.services.chat_service.chat_service.get_provider_instance') as mock_get_provider:
        mock_provider = AsyncMock()
        mock_provider.chat_completions.return_value = mock_streaming_response
        mock_get_provider.return_value = mock_provider
        
        # Мокаем stream_processor
        with patch.object(chat_service.stream_processor, 'process_stream') as mock_process_stream:
            # Настраиваем мок для process_stream
            async def mock_process_stream(chunks, model, request_id, user_id):
                # Проверяем, что все chunks доступны
                collected_chunks = []
                async for chunk in chunks:
                    collected_chunks.append(chunk)
                return collected_chunks
            
            mock_process_stream.side_effect = mock_process_stream
            
            # Выполняем запрос
            auth_data = ("test-project", "test-api-key", ["test-model"], [])
            response = await chat_service.chat_completions(mock_request, auth_data)
            
            # Проверяем результат
            assert isinstance(response, StreamingResponse)
            
            # Проверяем, что process_stream был вызван
            mock_process_stream.assert_called_once()
            
            # Получаем chunks, переданные в process_stream
            call_args = mock_process_stream.call_args
            chunks_iterator = call_args[0][0]  # Первый аргумент - итератор chunks
            
            # Собираем все chunks из итератора
            collected_chunks = []
            async for chunk in chunks_iterator:
                collected_chunks.append(chunk)
            
            # Проверяем, что все chunks доступны (первый не "съеден")
            assert len(collected_chunks) == len(test_chunks), f"Expected {len(test_chunks)} chunks, got {len(collected_chunks)}"
            
            # Проверяем содержимое первого chunk
            assert collected_chunks[0] == test_chunks[0], "First chunk was modified"
            
            print(f"✅ Все {len(test_chunks)} chunks доступны без изменений")
            print(f"✅ Первый chunk: {collected_chunks[0]}")
            
            # Проверяем DEBUG логи
            with open('logs/debug.log', 'r') as f:
                debug_logs = f.read()
                
                # Проверяем наличие лога о начале стриминга
                assert "DEBUG: Streaming Response Started" in debug_logs, "Streaming start log not found"
                assert "streaming\": true" in debug_logs, "Streaming flag not found in debug log"
                
                print("✅ DEBUG лог стриминга создан корректно")
    
    print("\n=== Тестирование завершено ===")
    print("✅ Проблема с 'съеданием' первого токена исправлена")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_streaming_fix())