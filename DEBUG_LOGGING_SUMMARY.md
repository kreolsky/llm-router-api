# Резюме реализации DEBUG логирования

## Задача

Добавить новый DEBUG уровень логирования, который будет логировать абсолютно все JSON-данные, проходящие через сервис: от клиента, к провайдерам и от провайдеров. Это поможет отловить редкий баг.

## Реализация

### 1. Модификация системы логирования
- Расширен `JsonFormatter` для поддержки DEBUG полей
- Обновлена функция `setup_logging()` для создания отдельного файла `debug.log`
- Добавлено чтение уровня логирования из переменной окружения `LOG_LEVEL`

### 2. Точки логирования
Добавлено DEBUG логирование в:
- **Middleware** (`src/api/middleware.py`) - входящие запросы
- **ChatService** (`src/services/chat_service/chat_service.py`) - запросы/ответы чата
- **EmbeddingService** (`src/services/embedding_service.py`) - запросы/ответы эмбеддингов
- **TranscriptionService** (`src/services/transcription_service.py`) - параметры запросов и ответы
- **BaseProvider** (`src/providers/base.py`) - запросы к провайдерам и их ответы
- **OpenAI Provider** (`src/providers/openai.py`) - полные запросы/ответы к OpenAI

### 3. Конфигурация
- Добавлена переменная `LOG_LEVEL` в файл `.env`
- По умолчанию установлен уровень `INFO`
- При `LOG_LEVEL=DEBUG` создается отдельный файл `logs/debug.log`

### 4. Формат логов
Каждый DEBUG лог содержит:
- `debug_json_data` - полные JSON данные без изменений
- `debug_data_flow` - направление потока данных (incoming/outgoing/to_provider/from_provider)
- `debug_component` - компонент, сгенерировавший лог
- `request_id` - уникальный идентификатор запроса

## Использование

### Включение
```bash
# Через переменную окружения
export LOG_LEVEL=DEBUG
python -m uvicorn src.api.main:app --reload

# Или через .env файл
LOG_LEVEL=DEBUG
```

### Просмотр логов
```bash
# Основные логи
tail -f logs/app.log

# DEBUG логи с полными JSON данными
tail -f logs/debug.log
```

### Поиск
```bash
# Поиск по request_id
grep "request_id\":\"your-request-id\" logs/debug.log

# Поиск по компоненту
grep "debug_component\":\"chat_service\" logs/debug.log
```

## Тестирование

Создан простой тест для проверки работы:
```bash
python test_debug_simple.py
```

Тест проверяет:
- Переключение между INFO и DEBUG режимами
- Правильность форматирования логов
- Создание файла debug.log

## Безопасность

⚠️ **Важно**: DEBUG логи содержат все данные включая чувствительную информацию.
- Использовать только в контролируемой среде
- Не использовать в продакшене
- Регулярно удалять старые логи

## Файлы

### Измененные файлы:
- `src/logging/config.py` - расширена система логирования
- `src/api/middleware.py` - добавлено DEBUG логирование запросов
- `src/services/chat_service/chat_service.py` - добавлено DEBUG логирование
- `src/services/embedding_service.py` - добавлено DEBUG логирование
- `src/services/transcription_service.py` - добавлено DEBUG логирование
- `src/providers/base.py` - добавлено DEBUG логирование запросов к провайдерам
- `src/providers/openai.py` - добавлено DEBUG логирование ответов от провайдера
- `.env` - добавлена переменная LOG_LEVEL

### Новые файлы:
- `docs/debug_logging_design.md` - детальная архитектура
- `docs/debug_logging_flow_diagram.md` - диаграммы потока данных
- `docs/debug_logging_implementation_guide.md` - руководство по реализации
- `tests/test_debug_logging.py` - тесты для pytest
- `test_debug_simple.py` - простой тест для проверки
- `DEBUG_LOGGING_USAGE.md` - инструкция по использованию
- `DEBUG_LOGGING_SUMMARY.md` - это резюме

## Результат

✅ **Реализована полная система DEBUG логирования**:
- Логируются все JSON-данные без изменений
- Создается отдельный файл debug.log
- Есть возможность включения/выключения через конфигурацию
- Минимальное влияние на производительность в обычном режиме

Теперь можно отлавливать редкие баги, анализируя полный поток данных через сервис.