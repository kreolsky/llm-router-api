# Упрощенный дизайн единой системы логирования

## Проблема

В текущей реализации есть две независимые системы логирования:
1. Основная система в `src/core/logging/config.py`
2. ErrorLogger в `src/core/error_handling/error_logger.py`, который создает свой собственный логгер

Это приводит к разному поведению и форматированию логов.

## Простое решение

### 1. Модифицируем `setup_logging()` в `src/core/logging/config.py`

```python
def setup_logging():
    """Единая настройка логирования для всего проекта."""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    
    # Создаем основной логгер
    logger = logging.getLogger("nnp-llm-router")
    logger.setLevel(getattr(logging, log_level))
    
    # Очищаем существующие обработчики
    logger.handlers.clear()
    
    # Создаем директорию для логов
    LOG_DIR = "logs"
    os.makedirs(LOG_DIR, exist_ok=True)
    
    # Единый форматтер для всех обработчиков
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z"
    )
    
    # Файловый обработчик (всегда)
    file_handler = logging.FileHandler(os.path.join(LOG_DIR, "app.log"))
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    
    # Обработчик для DEBUG (если включен)
    if log_level == "DEBUG":
        debug_handler = logging.FileHandler(os.path.join(LOG_DIR, "debug.log"))
        debug_handler.setFormatter(formatter)
        debug_handler.setLevel(logging.DEBUG)
        logger.addHandler(debug_handler)
    
    # Консольный обработчик (уровень зависит от LOG_LEVEL)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.DEBUG if log_level == "DEBUG" else logging.INFO)
    logger.addHandler(console_handler)
    
    return logger
```

### 2. Модифицируем `ErrorLogger` в `src/core/error_handling/error_logger.py`

```python
from ..logging.config import setup_logging

class ErrorLogger:
    """Единый логгер ошибок, использующий общую систему."""
    
    @staticmethod
    def _get_logger():
        """Получить логгер из единой системы."""
        return setup_logging()
    
    @staticmethod
    def log_error(error_type, context, original_exception=None, additional_data=None):
        """Логировать ошибку с использованием единой системы."""
        logger = ErrorLogger._get_logger()
        
        log_extra = context.to_log_extra()
        log_extra["error_type"] = error_type.code
        log_extra["error_code"] = error_type.code
        log_extra["http_status_code"] = error_type.status_code
        
        if additional_data:
            log_extra.update(additional_data)
        
        log_message = f"{error_type.format_message(**context.__dict__)}"
        
        if original_exception:
            log_extra["original_exception"] = str(original_exception)
            log_extra["original_exception_type"] = type(original_exception).__name__
            logger.error(log_message, extra=log_extra, exc_info=True)
        else:
            logger.error(log_message, extra=log_extra)
```

### 3. Обновляем `src/core/logging/__init__.py`

```python
from .config import setup_logging
from .logger import Logger

# Создаем единый экземпляр логгера
_logger_instance = None

def get_logger():
    """Получить единый экземпляр логгера."""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = Logger()
    return _logger_instance

# Экспортируем единый логгер
logger = get_logger()

__all__ = ['logger', 'Logger', 'setup_logging']
```

## Преимущества упрощенного подхода

1. **Минимум изменений**: Только 2 файла нужно изменить
2. **Единая точка настройки**: Вся конфигурация в `setup_logging()`
3. **Простота**: Нет сложных фабрик и менеджеров
4. **Гарантированная работа**: ErrorLogger всегда использует те же обработчики
5. **Сохранение функциональности**: Все существующие возможности сохраняются

## План миграции

1. Изменить `setup_logging()` для поддержки всех нужных обработчиков
2. Изменить `ErrorLogger` для использования `setup_logging()`
3. Обновить импорты в `__init__.py`
4. Протестировать работу системы

## Результат

При `LOG_LEVEL=DEBUG`:
- Консоль: все логи (DEBUG и выше)
- Файл `app.log`: INFO и выше
- Файл `debug.log`: только DEBUG

При `LOG_LEVEL=INFO`:
- Консоль: INFO и выше
- Файл `app.log`: INFO и выше
- Файл `debug.log`: не создается

Все логи используют одинаковый формат и обрабатываются единой системой.