# Конфигурируемая система санитизации сообщений

## Архитектура решения

Создаем систему санитизации сообщений, которая активируется через переменную окружения, аналогично режиму отладки.

## Компоненты системы

### 1. Переменная окружения

```bash
# В .env файле
SANITIZE_MESSAGES=true  # или false для отключения
```

### 2. Конфигурационный менеджер

В `src/core/config_manager.py` добавить чтение флага:

```python
class ConfigManager:
    def __init__(self):
        # ... существующий код ...
        self.sanitize_messages = os.getenv("SANITIZE_MESSAGES", "false").lower() == "true"
    
    @property
    def should_sanitize_messages(self) -> bool:
        """Возвращает True если нужно санитизировать сообщения"""
        return self.sanitize_messages
```

### 3. Система санитизации

В `src/services/chat_service/sanitizer.py` создать модуль:

```python
"""
Модуль санитизации сообщений от клиентской контаминации
"""

import logging
from typing import Dict, Any, List
from ..logging.config import logger

class MessageSanitizer:
    """Класс для очистки сообщений от нестандартных полей"""
    
    # Список полей, которые нужно удалять из сообщений
    SERVICE_FIELDS = ['done', '__stream_end__', '__internal__', 'stream_end']
    
    @classmethod
    def sanitize_messages(cls, messages: List[Dict[str, Any]], enabled: bool = True) -> List[Dict[str, Any]]:
        """
        Очищает сообщения от служебных полей если санитизация включена
        
        Args:
            messages: Список сообщений для очистки
            enabled: Включена ли санитизация
            
        Returns:
            Очищенный список сообщений
        """
        if not enabled:
            logger.debug("Message sanitization is disabled")
            return messages
        
        logger.debug(f"Sanitizing {len(messages)} messages from client-side contamination")
        sanitized = []
        removed_fields_count = 0
        
        for i, message in enumerate(messages):
            clean_message = message.copy()
            removed_in_message = []
            
            # Удаляем известные служебные поля
            for field in cls.SERVICE_FIELDS:
                if field in clean_message:
                    removed_in_message.append(field)
                    clean_message.pop(field, None)
                    removed_fields_count += 1
            
            # Логируем удаленные поля для отладки
            if removed_in_message:
                logger.debug(f"Removed fields {removed_in_message} from message {i}")
            
            sanitized.append(clean_message)
        
        if removed_fields_count > 0:
            logger.info(f"Message sanitization removed {removed_fields_count} service fields from {len(messages)} messages")
        
        return sanitized
```

### 4. Интеграция в провайдер

В `src/providers/openai.py` интегрировать санитизацию:

```python
from ..services.chat_service.sanitizer import MessageSanitizer

class OpenAICompatibleProvider(BaseProvider):
    async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
        # ... существующий код ...
        
        # САНИТИЗАЦИЯ СООБЩЕНИЙ (если включена)
        if "messages" in request_body and hasattr(self, 'config_manager'):
            sanitize_enabled = self.config_manager.should_sanitize_messages
            request_body["messages"] = MessageSanitizer.sanitize_messages(
                request_body["messages"], 
                enabled=sanitize_enabled
            )
        
        # ... остальной код ...
```

### 5. Передача конфигурации в провайдеры

В `src/services/chat_service/chat_service.py` или при инициализации провайдеров:

```python
# При создании провайдера передаем ConfigManager
provider = OpenAICompatibleProvider(config, client)
provider.config_manager = app.state.config_manager  # Передаем ссылку
```

### 6. Логирование системы

Добавить логирование для отслеживания работы системы:

```python
# При старте приложения
logger.info(f"Message sanitization: {'ENABLED' if config_manager.should_sanitize_messages else 'DISABLED'}")

# При обработке запроса
if config_manager.should_sanitize_messages:
    logger.debug(f"Request {request_id}: Message sanitization is active")
```

## Конфигурация для разных окружений

### Разработка (.env.development)
```bash
SANITIZE_MESSAGES=true
DEBUG=true
```

### Тестирование (.env.testing)
```bash
SANITIZE_MESSAGES=true
DEBUG=false
```

### Продакшн (.env.production)
```bash
SANITIZE_MESSAGES=false  # Отключаем если клиенты исправлены
DEBUG=false
```

## Преимущества этой архитектуры

1. **Гибкость**: Можно включать/выключать санитизацию без переразвертывания
2. **Отладка**: Логирование показывает, какие поля удаляются
3. **Безопасность**: По умолчанию можно отключить в продакшне
4. **Тестируемость**: Легко тестировать с разными настройками
5. **Производительность**: Нулевые накладные расходы при отключении

## Тестирование системы

```python
def test_sanitization_system():
    """Тест конфигурируемой системы санитизации"""
    
    # Тест с включенной санитизацией
    config_manager = ConfigManager()
    config_manager.sanitize_messages = True
    
    contaminated_messages = [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "", "done": false}
    ]
    
    sanitized = MessageSanitizer.sanitize_messages(
        contaminated_messages, 
        enabled=config_manager.should_sanitize_messages
    )
    
    assert "done" not in sanitized[2]
    
    # Тест с отключенной санитизацией
    config_manager.sanitize_messages = False
    not_sanitized = MessageSanitizer.sanitize_messages(
        contaminated_messages, 
        enabled=config_manager.should_sanitize_messages
    )
    
    assert "done" in not_sanitized[2]  # Поле должно остаться
```

## План внедрения

1. **Создать модуль санитизации** (`src/services/chat_service/sanitizer.py`)
2. **Добавить флаг в ConfigManager** (`src/core/config_manager.py`)
3. **Интегрировать в OpenAI провайдер** (`src/providers/openai.py`)
4. **Обновить инициализацию провайдеров** для передачи ConfigManager
5. **Добавить переменную в .env** (`SANITIZE_MESSAGES=true`)
6. **Создать тесты** для проверки работы системы
7. **Добавить логирование** для мониторинга

Эта система позволит гибко управлять санитизацией и будет полезна не только для текущей проблемы с OpenRouter, но и для будущих случаев клиентской контаминации.