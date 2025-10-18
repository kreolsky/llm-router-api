#!/usr/bin/env python3
"""
Демонстрация работы санитизации сообщений
"""

import sys
import os
import json
import asyncio
import logging
sys.path.append('.')

from src.core.sanitizer import MessageSanitizer
from src.services.chat_service.stream_processor import StreamProcessor
from src.core.config_manager import ConfigManager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def demo_sanitization():
    """Демонстрация работы санитизации"""
    logger.info("🧪 Демонстрация санитизации стриминговых чанков")
    
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
    
    logger.info("📥 Оригинальный чанк:")
    logger.info(json.dumps(contaminated_chunk, indent=2))
    
    # Применяем санитизацию
    sanitized_chunk = MessageSanitizer.sanitize_stream_chunk(contaminated_chunk, enabled=True)
    
    logger.info("📤 Санитизированный чанк:")
    logger.info(json.dumps(sanitized_chunk, indent=2))
    
    # Показываем, что было удалено
    original_delta = contaminated_chunk["choices"][0]["delta"]
    sanitized_delta = sanitized_chunk["choices"][0]["delta"]
    
    removed_fields = []
    for field in original_delta:
        if field not in sanitized_delta:
            removed_fields.append(field)
    
    logger.info(f"🗑️ Удаленные поля: {removed_fields}")
    logger.info(f"✅ Сохраненные поля: {list(sanitized_delta.keys())}")


def demo_stream_processing():
    """Демонстрация обработки стрима"""
    logger.info("🌊 Демонстрация обработки стрима")
    
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
            logger.info(f"📥 Получен чанк: {chunk.decode('utf-8').strip()}")
            yield chunk
    
    # Обрабатываем стрим
    logger.info("🔄 Обработка стрима с санитизацией...")
    
    async def process():
        chunk_count = 0
        async for chunk in processor.process_stream(mock_stream(), "test_model", "req_123", "user_123"):
            chunk_count += 1
            logger.info(f"📤 Отправлен чанк {chunk_count}: {chunk.decode('utf-8').strip()}")
    
    asyncio.run(process())
    
    # Показываем статистику
    stats = processor.get_processing_stats()
    logger.info("📊 Статистика обработки:")
    logger.info(f"  Всего чанков: {stats['total_chunks_processed']}")
    logger.info(f"  Санитизировано: {stats['total_chunks_sanitized']}")
    logger.info(f"  Рatio санитизации: {stats['sanitization_ratio']:.2%}")
    logger.info(f"  Санитизация включена: {stats['sanitization_enabled']}")


def demo_provider_compatibility():
    """Демонстрация совместимости с провайдерами"""
    logger.info("🔌 Демонстрация совместимости с провайдерами")
    
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
    
    logger.info("🔴 OpenRouter (строгий валидатор):")
    logger.info("  До санитизации: содержит поля 'done' и '__internal__' → 400 Bad Request")
    
    sanitized = MessageSanitizer.sanitize_stream_chunk(openrouter_chunk, enabled=True)
    logger.info("  После санитизации: только 'content' → Успешный запрос")
    
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
    
    logger.info("🟡 Anthropic (гибкий, но лучше чистить):")
    logger.info("  До санитизации: содержит reasoning_content и служебные поля")
    
    sanitized = MessageSanitizer.sanitize_stream_chunk(anthropic_chunk, enabled=True)
    logger.info("  После санитизации: reasoning_content сохранен, служебные поля удалены")
    
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
    
    logger.info("🟢 Ollama (толерантный):")
    logger.info("  До санитизации: содержит done и custom_field")
    
    sanitized = MessageSanitizer.sanitize_stream_chunk(ollama_chunk, enabled=True)
    logger.info("  После санитизации: done удален, custom_field сохранен")


def main():
    """Запуск всех демонстраций"""
    logger.info("🎯 Демонстрация санитизации сообщений для потоковой выдачи")
    logger.info("=" * 60)
    
    demo_sanitization()
    demo_stream_processing()
    demo_provider_compatibility()
    
    logger.info("=" * 60)
    logger.info("✅ Демонстрация завершена!")
    logger.info("💡 Ключевые преимущества:")
    logger.info("  • Совместимость со строгими провайдерами (OpenRouter)")
    logger.info("  • Сохранение полезного контента (content, reasoning_content)")
    logger.info("  • Управление через флаг SANITIZE_MESSAGES")
    logger.info("  • Прозрачность для tolerant провайдеров")
    logger.info("  • Минимальное влияние на производительность")


if __name__ == "__main__":
    main()