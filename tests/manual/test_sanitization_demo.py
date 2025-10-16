#!/usr/bin/env python3
"""
Демонстрация работы санитизации сообщений
"""

import sys
import os
import json
import asyncio
sys.path.append('.')

from src.core.sanitizer import MessageSanitizer
from src.services.chat_service.stream_processor import StreamProcessor
from src.core.config_manager import ConfigManager


def demo_sanitization():
    """Демонстрация работы санитизации"""
    print("🧪 Демонстрация санитизации стриминговых чанков\n")
    
    # Пример загрязненного чанка от клиента
    contaminated_chunk = {
        "choices": [{
            "index": 0,
            "delta": {
                "content": "Hello",
                "reasoning_content": "Let me think...",
                "done": True,  # Проблемное поле для OpenRouter
                "__internal__": "secret_data",  # Внутреннее поле
                "stream_end": True,  # Еще одно проблемное поле
                "__stream_end__": True  # И еще одно
            },
            "finish_reason": "stop"
        }]
    }
    
    print("📥 Оригинальный чанк:")
    print(json.dumps(contaminated_chunk, indent=2))
    
    # Применяем санитизацию
    sanitized_chunk = MessageSanitizer.sanitize_stream_chunk(contaminated_chunk, enabled=True)
    
    print("\n📤 Санитизированный чанк:")
    print(json.dumps(sanitized_chunk, indent=2))
    
    # Показываем, что было удалено
    original_delta = contaminated_chunk["choices"][0]["delta"]
    sanitized_delta = sanitized_chunk["choices"][0]["delta"]
    
    removed_fields = []
    for field in original_delta:
        if field not in sanitized_delta:
            removed_fields.append(field)
    
    print(f"\n🗑️ Удаленные поля: {removed_fields}")
    print(f"✅ Сохраненные поля: {list(sanitized_delta.keys())}")


def demo_stream_processing():
    """Демонстрация обработки стрима"""
    print("\n🌊 Демонстрация обработки стрима\n")
    
    # Создаем конфигурацию с включенной санитизацией
    os.environ["SANITIZE_MESSAGES"] = "true"
    config_manager = ConfigManager()
    
    # Создаем StreamProcessor
    processor = StreamProcessor(config_manager)
    
    # Эмулируем стрим с загрязненными данными
    async def mock_stream():
        chunks = [
            b'data: {"choices":[{"index":0,"delta":{"content":"Hello","done":true}}]}\n\n',
            b'data: {"choices":[{"index":0,"delta":{"reasoning_content":"thinking","__internal__":"data"}}]}\n\n',
            b'data: {"choices":[{"index":0,"delta":{"content":" world","stream_end":true}}]}\n\n',
            b'data: [DONE]\n\n'
        ]
        
        for chunk in chunks:
            print(f"📥 Получен чанк: {chunk.decode('utf-8').strip()}")
            yield chunk
    
    # Обрабатываем стрим
    print("🔄 Обработка стрима с санитизацией...")
    
    async def process():
        chunk_count = 0
        async for chunk in processor.process_stream(mock_stream(), "test_model", "req_123", "user_123"):
            chunk_count += 1
            print(f"📤 Отправлен чанк {chunk_count}: {chunk.decode('utf-8').strip()}")
    
    asyncio.run(process())
    
    # Показываем статистику
    stats = processor.get_processing_stats()
    print(f"\n📊 Статистика обработки:")
    print(f"  Всего чанков: {stats['total_chunks_processed']}")
    print(f"  Санитизировано: {stats['total_chunks_sanitized']}")
    print(f"  Рatio санитизации: {stats['sanitization_ratio']:.2%}")
    print(f"  Санитизация включена: {stats['sanitization_enabled']}")


def demo_provider_compatibility():
    """Демонстрация совместимости с провайдерами"""
    print("\n🔌 Демонстрация совместимости с провайдерами\n")
    
    # OpenRouter - строгий валидатор
    openrouter_chunk = {
        "choices": [{
            "index": 0,
            "delta": {
                "content": "Response from OpenRouter",
                "done": True,  # Вызовет 400 ошибку
                "__internal__": "client_data"  # Тоже проблема
            }
        }]
    }
    
    print("🔴 OpenRouter (строгий валидатор):")
    print("  До санитизации: содержит поля 'done' и '__internal__' → 400 Bad Request")
    
    sanitized = MessageSanitizer.sanitize_stream_chunk(openrouter_chunk, enabled=True)
    print("  После санитизации: только 'content' → Успешный запрос")
    
    # Anthropic - более гибкий
    anthropic_chunk = {
        "choices": [{
            "index": 0,
            "delta": {
                "content": "Response",
                "reasoning_content": "Complex reasoning",
                "done": True,  # Лучше удалить
                "__internal__": "metadata"
            }
        }]
    }
    
    print("\n🟡 Anthropic (гибкий, но лучше чистить):")
    print("  До санитизации: содержит reasoning_content и служебные поля")
    
    sanitized = MessageSanitizer.sanitize_stream_chunk(anthropic_chunk, enabled=True)
    print("  После санитизации: reasoning_content сохранен, служебные поля удалены")
    
    # Ollama - толерантный
    ollama_chunk = {
        "choices": [{
            "index": 0,
            "delta": {
                "content": "Local response",
                "done": True,
                "custom_field": "preserved"  # Не в списке SERVICE_FIELDS
            }
        }]
    }
    
    print("\n🟢 Ollama (толерантный):")
    print("  До санитизации: содержит done и custom_field")
    
    sanitized = MessageSanitizer.sanitize_stream_chunk(ollama_chunk, enabled=True)
    print("  После санитизации: done удален, custom_field сохранен")


def main():
    """Запуск всех демонстраций"""
    print("🎯 Демонстрация санитизации сообщений для потоковой выдачи")
    print("=" * 60)
    
    demo_sanitization()
    demo_stream_processing()
    demo_provider_compatibility()
    
    print("\n" + "=" * 60)
    print("✅ Демонстрация завершена!")
    print("\n💡 Ключевые преимущества:")
    print("  • Совместимость со строгими провайдерами (OpenRouter)")
    print("  • Сохранение полезного контента (content, reasoning_content)")
    print("  • Управление через флаг SANITIZE_MESSAGES")
    print("  • Прозрачность для tolerant провайдеров")
    print("  • Минимальное влияние на производительность")


if __name__ == "__main__":
    main()