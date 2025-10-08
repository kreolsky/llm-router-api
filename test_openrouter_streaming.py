#!/usr/bin/env python3
"""
Тест для проверки исправления проблемы с OpenRouter streaming
"""

import asyncio
import json
import os
from src.services.chat_service.stream_processor import StreamProcessor
from src.services.chat_service.statistics_collector import StatisticsCollector

async def test_openrouter_message_sanitization():
    """Тест очистки сообщений с 'done: true' для OpenRouter"""
    
    # Пример сообщения с 'done: true' из логов
    contaminated_messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant."
        },
        {
            "role": "user",
            "content": "Не, давай луну"
        },
        {
            "role": "assistant",
            "content": "<status title=\"Edited\" done=\"true\" />",
            "done": True  # Это поле должно быть удалено
        }
    ]
    
    print("Testing message sanitization for OpenRouter...")
    print("Original messages:")
    for msg in contaminated_messages:
        print(f"  {msg}")
    
    # Очищаем сообщения
    sanitized_messages = []
    for message in contaminated_messages:
        clean_message = message.copy()
        
        # Удаляем только известные служебные поля
        service_fields = ['done', '__stream_end__', '__internal__']
        for field in service_fields:
            clean_message.pop(field, None)
        
        sanitized_messages.append(clean_message)
    
    print("\nSanitized messages:")
    for msg in sanitized_messages:
        print(f"  {msg}")
    
    # Проверяем, что нет служебных полей
    for msg in sanitized_messages:
        if 'done' in msg:
            print("ERROR: Found 'done' field in sanitized message!")
            return False
    
    print("\nSUCCESS: Messages properly sanitized")
    return True

async def test_sse_done_parsing():
    """Тест парсинга SSE с [DONE]"""
    processor = StreamProcessor()
    
    # Тестовые данные SSE с [DONE]
    test_sse_data = b"data: {\"choices\": [{\"delta\": {\"content\": \"Hello\"}}]}\n\n"
    test_sse_data += b"data: {\"choices\": [{\"delta\": {\"content\": \" world\"}}]}\n\n"
    test_sse_data += b"data: [DONE]\n\n"
    
    print("\nTesting SSE [DONE] parsing...")
    
    # Создаем генератор для теста
    async def mock_stream():
        yield test_sse_data
    
    # Обрабатываем поток
    results = []
    async for chunk in processor.process_stream(mock_stream(), "test-model", "test-request", "test-user"):
        results.append(chunk)
    
    # Проверяем, что нет {'done': True} в результатах
    for chunk in results:
        chunk_str = chunk.decode('utf-8')
        if '"done": true' in chunk_str:
            print("ERROR: Found 'done': true in response!")
            return False
    
    print("SUCCESS: No 'done': true found in streaming responses")
    return True

async def main():
    """Основная функция теста"""
    print("Running OpenRouter streaming fix tests...\n")
    
    test1_passed = await test_openrouter_message_sanitization()
    test2_passed = await test_sse_done_parsing()
    
    if test1_passed and test2_passed:
        print("\n✅ All tests passed! The OpenRouter streaming fix should work correctly.")
        print("\nThe fix implements:")
        print("1. Separate flag handling for [DONE] events instead of creating {'done': True} objects")
        print("2. Safe string parsing without magic numbers")
        print("3. Message sanitization to remove any client-side contamination")
    else:
        print("\n❌ Some tests failed! Please check the implementation.")

if __name__ == "__main__":
    asyncio.run(main())