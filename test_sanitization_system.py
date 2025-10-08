#!/usr/bin/env python3
"""
Тест для проверки конфигурируемой системы санитизации сообщений
"""

import asyncio
import os
from src.services.chat_service.sanitizer import MessageSanitizer
from src.core.config_manager import ConfigManager

def test_sanitization_enabled():
    """Тест санитизации с включенным флагом"""
    # Загрязненные сообщения
    contaminated_messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant."
        },
        {
            "role": "user",
            "content": "Hello"
        },
        {
            "role": "assistant",
            "content": "",
            "done": False  # Это поле должно быть удалено
        }
    ]
    
    print("Testing sanitization with enabled flag...")
    print("Original messages:")
    for msg in contaminated_messages:
        print(f"  {msg}")
    
    # Включаем санитизацию
    sanitized = MessageSanitizer.sanitize_messages(contaminated_messages, enabled=True)
    
    print("\nSanitized messages:")
    for msg in sanitized:
        print(f"  {msg}")
    
    # Проверяем, что поле 'done' удалено
    for msg in sanitized:
        if 'done' in msg:
            print("ERROR: Found 'done' field in sanitized message!")
            return False
    
    print("SUCCESS: 'done' field properly removed")
    return True

def test_sanitization_disabled():
    """Тест санитизации с отключенным флагом"""
    # Загрязненные сообщения
    contaminated_messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant."
        },
        {
            "role": "user",
            "content": "Hello"
        },
        {
            "role": "assistant",
            "content": "",
            "done": False  # Это поле должно остаться
        }
    ]
    
    print("\nTesting sanitization with disabled flag...")
    print("Original messages:")
    for msg in contaminated_messages:
        print(f"  {msg}")
    
    # Отключаем санитизацию
    not_sanitized = MessageSanitizer.sanitize_messages(contaminated_messages, enabled=False)
    
    print("\nNot sanitized messages:")
    for msg in not_sanitized:
        print(f"  {msg}")
    
    # Проверяем, что поле 'done' осталось
    found_done = False
    for msg in not_sanitized:
        if 'done' in msg:
            found_done = True
            break
    
    if not found_done:
        print("ERROR: 'done' field was removed when sanitization was disabled!")
        return False
    
    print("SUCCESS: 'done' field preserved when sanitization disabled")
    return True

def test_config_manager():
    """Тест чтения флага из ConfigManager"""
    print("\nTesting ConfigManager integration...")
    
    # Временная установка переменной окружения
    original_value = os.getenv("SANITIZE_MESSAGES")
    
    try:
        # Тест с включенным флагом
        os.environ["SANITIZE_MESSAGES"] = "true"
        config_manager = ConfigManager()
        
        if not config_manager.should_sanitize_messages:
            print("ERROR: ConfigManager should return True when SANITIZE_MESSAGES=true")
            return False
        
        print("SUCCESS: ConfigManager correctly reads SANITIZE_MESSAGES=true")
        
        # Тест с отключенным флагом
        os.environ["SANITIZE_MESSAGES"] = "false"
        config_manager = ConfigManager()
        
        if config_manager.should_sanitize_messages:
            print("ERROR: ConfigManager should return False when SANITIZE_MESSAGES=false")
            return False
        
        print("SUCCESS: ConfigManager correctly reads SANITIZE_MESSAGES=false")
        
    finally:
        # Восстанавливаем исходное значение
        if original_value is not None:
            os.environ["SANITIZE_MESSAGES"] = original_value
        elif "SANITIZE_MESSAGES" in os.environ:
            del os.environ["SANITIZE_MESSAGES"]
    
    return True

def main():
    """Основная функция теста"""
    print("Running configurable sanitization system tests...\n")
    
    test1_passed = test_sanitization_enabled()
    test2_passed = test_sanitization_disabled()
    test3_passed = test_config_manager()
    
    if test1_passed and test2_passed and test3_passed:
        print("\n✅ All tests passed! The configurable sanitization system works correctly.")
        print("\nThe system implements:")
        print("1. Configurable message sanitization based on SANITIZE_MESSAGES flag")
        print("2. Selective removal of service fields only when enabled")
        print("3. Zero overhead when sanitization is disabled")
        print("4. Integration with ConfigManager for flag management")
    else:
        print("\n❌ Some tests failed! Please check the implementation.")

if __name__ == "__main__":
    main()