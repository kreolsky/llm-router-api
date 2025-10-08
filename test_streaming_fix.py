#!/usr/bin/env python3
"""
Тест для проверки исправления проблемы с OpenRouter streaming
"""

import asyncio
import json
from src.services.chat_service.stream_processor import StreamProcessor
from src.services.chat_service.statistics_collector import StatisticsCollector

async def test_sse_parsing():
    """Тест парсинга SSE событий с новым подходом"""
    processor = StreamProcessor()
    
    # Тестовые данные SSE с [DONE]
    test_sse_data = b"data: {\"choices\": [{\"delta\": {\"content\": \"Hello\"}}]}\n\n"
    test_sse_data += b"data: {\"choices\": [{\"delta\": {\"content\": \" world\"}}]}\n\n"
    test_sse_data += b"data: [DONE]\n\n"
    
    print("Testing SSE parsing with new approach...")
    
    # Создаем генератор для теста
    async def mock_stream():
        yield test_sse_data
    
    # Обрабатываем поток
    results = []
    async for chunk in processor.process_stream(mock_stream(), "test-model", "test-request", "test-user"):
        results.append(chunk)
        print(f"Received chunk: {chunk}")
    
    # Проверяем результаты
    print(f"Total chunks received: {len(results)}")
    
    # Проверяем, что нет {'done': True} в результатах
    for chunk in results:
        chunk_str = chunk.decode('utf-8')
        if '"done": true' in chunk_str:
            print("ERROR: Found 'done': true in response!")
            return False
    
    print("SUCCESS: No 'done': true found in responses")
    return True

async def test_sse_event_parsing():
    """Тест парсинга отдельных SSE событий"""
    processor = StreamProcessor()
    
    # Тестовое событие [DONE]
    done_event = "data: [DONE]"
    
    # Тестовое обычное событие
    normal_event = "data: {\"choices\": [{\"delta\": {\"content\": \"Hello\"}}]}"
    
    print("\nTesting individual SSE event parsing...")
    
    # Тест парсинга [DONE]
    event_data, is_done = processor._parse_sse_event(done_event)
    print(f"[DONE] event - data: {event_data}, is_done: {is_done}")
    
    if event_data is not None or not is_done:
        print("ERROR: [DONE] event not parsed correctly!")
        return False
    
    # Тест парсинга обычного события
    event_data, is_done = processor._parse_sse_event(normal_event)
    print(f"Normal event - data: {event_data}, is_done: {is_done}")
    
    if event_data is None or is_done:
        print("ERROR: Normal event not parsed correctly!")
        return False
    
    print("SUCCESS: Individual event parsing works correctly")
    return True

async def main():
    """Основная функция теста"""
    print("Running streaming fix tests...\n")
    
    test1_passed = await test_sse_event_parsing()
    test2_passed = await test_sse_parsing()
    
    if test1_passed and test2_passed:
        print("\n✅ All tests passed! The streaming fix should work correctly.")
    else:
        print("\n❌ Some tests failed! Please check the implementation.")

if __name__ == "__main__":
    asyncio.run(main())