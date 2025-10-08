#!/usr/bin/env python3
"""
Простой тест для проверки работы DEBUG логирования
"""

import os
import sys
import logging
import tempfile

# Добавляем src в путь
sys.path.append('src')

from src.logging.config import setup_logging, logger


def test_debug_logging():
    """Тестирование функциональности DEBUG логирования"""
    print("=== Тестирование DEBUG логирования ===")
    
    # Тест 1: INFO режим
    print("\n1. Тест INFO режима:")
    os.environ["LOG_LEVEL"] = "INFO"
    setup_logging()
    
    print(f"   Уровень логера: {logger.level}")
    print(f"   DEBUG включен: {logger.isEnabledFor(logging.DEBUG)}")
    
    # Тестовое сообщение в INFO режиме
    logger.debug("DEBUG: Это сообщение не должно появиться в логах")
    print("   DEBUG сообщение отправлено (не должно появиться в логах)")
    
    # Тест 2: DEBUG режим
    print("\n2. Тест DEBUG режима:")
    os.environ["LOG_LEVEL"] = "DEBUG"
    setup_logging()
    
    print(f"   Уровень логера: {logger.level}")
    print(f"   DEBUG включен: {logger.isEnabledFor(logging.DEBUG)}")
    
    # Тестовое сообщение в DEBUG режиме
    test_data = {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hello"}],
        "temperature": 0.7
    }
    
    logger.debug(
        "DEBUG: Test Request JSON",
        extra={
            "debug_json_data": test_data,
            "debug_data_flow": "incoming",
            "debug_component": "test_component",
            "request_id": "test-123"
        }
    )
    print("   DEBUG сообщение отправлено с JSON данными")
    
    # Тест 3: Проверка формата лога
    print("\n3. Тест формата лога:")
    logger.debug(
        "DEBUG: Format Test",
        extra={
            "debug_json_data": {"test": "format"},
            "debug_data_flow": "test_flow",
            "debug_component": "test_component"
        }
    )
    
    print("\n=== Тестирование завершено ===")
    print("Проверьте файлы logs/app.log и logs/debug.log для результатов")


if __name__ == "__main__":
    test_debug_logging()