# Использование DEBUG логирования в NNp LLM Router

## Обзор

Система DEBUG логирования позволяет логировать все JSON-данные, проходящие через сервис, что необходимо для отлова редких багов.

## Включение DEBUG логирования

### Способ 1: Через переменную окружения

```bash
# Включить DEBUG логирование
export LOG_LEVEL=DEBUG
python -m uvicorn src.api.main:app --reload

# Или для Docker
docker compose up -d  # с LOG_LEVEL=DEBUG в .env файле
```

### Способ 2: Через файл .env

Отредактируйте файл `.env`:
```env
LOG_LEVEL=DEBUG
```

## Просмотр логов

### Основные логи (INFO/ERROR)
```bash
tail -f logs/app.log
```

### DEBUG логи (полные JSON данные)
```bash
tail -f logs/debug.log
```

## Формат DEBUG логов

Каждый DEBUG лог содержит:
- `timestamp`: Время события
- `level`: Уровень логирования (DEBUG)
- `message`: Описание события
- `debug_json_data`: Полные JSON данные без изменений
- `debug_data_flow`: Направление потока данных
  - `incoming` - данные от клиента
  - `outgoing` - данные к клиенту
  - `to_provider` - данные к провайдеру
  - `from_provider` - данные от провайдера
- `debug_component`: Компонент, сгенерировавший лог
- `request_id`: Уникальный идентификатор запроса

### Пример DEBUG лога

```json
{
  "timestamp": "2025-10-08T17:14:49+0300",
  "level": "DEBUG",
  "message": "DEBUG: Chat Completion Request JSON",
  "request_id": "test-123",
  "debug_json_data": {
    "model": "openai/gpt-4",
    "messages": [
      {"role": "user", "content": "Hello"}
    ],
    "temperature": 0.7,
    "max_tokens": 1000
  },
  "debug_data_flow": "incoming",
  "debug_component": "chat_service"
}
```

## Поиск в логах

### Поиск по request_id
```bash
grep "request_id\":\"your-request-id\" logs/debug.log
```

### Поиск по компоненту
```bash
grep "debug_component\":\"chat_service\" logs/debug.log
```

### Построение цепочки запроса
```bash
# Извлечение request_id из всех логов
grep -o "request_id\":\"[^\"]*" logs/debug.log | sort | uniq

# Просмотр полного потока для конкретного запроса
grep "request_id\":\"your-request-id\" logs/debug.log | jq '.debug_data_flow, .debug_component'
```

## Отключение DEBUG логирования

```bash
# Установить уровень INFO
export LOG_LEVEL=INFO
python -m uvicorn src.api.main:app --reload

# Или изменить в .env файле
LOG_LEVEL=INFO
```

## Важные замечания

⚠️ **Внимание**: DEBUG логи содержат все данные включая чувствительную информацию. Использовать только в контролируемой среде.

1. **Производительность**: DEBUG логирование может незначительно влиять на производительность
2. **Размер логов**: DEBUG логи могут быстро увеличиваться в размере
3. **Безопасность**: Не использовать DEBUG логирование в продакшене

## Тестирование

Для проверки работы DEBUG логирования:
```bash
python test_debug_simple.py
```

## Компоненты с DEBUG логированием

- `middleware` - входящие/исходящие запросы
- `chat_service` - обработка запросов чата
- `embedding_service` - обработка эмбеддингов
- `transcription_service` - обработка транскрипции
- `base_provider` - базовые запросы к провайдерам
- `openai_provider` - запросы к OpenAI API

## Диагностика проблем

Если DEBUG логи не появляются:

1. Проверьте переменную окружения:
   ```bash
   echo $LOG_LEVEL
   ```

2. Проверьте права записи в директорию logs:
   ```bash
   ls -la logs/
   ```

3. Перезапустите сервис после изменения LOG_LEVEL