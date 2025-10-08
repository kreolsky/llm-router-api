# Руководство по реализации DEBUG логирования

## Краткое описание

Этот документ содержит пошаговую инструкцию по реализации системы DEBUG логирования для NNp LLM Router.

## Порядок реализации

### 1. Модификация системы логирования (src/logging/config.py)

```python
# В класс JsonFormatter добавить поддержку DEBUG полей:
if hasattr(record, 'debug_json_data'):
    log_record['debug_json_data'] = record.debug_json_data
if hasattr(record, 'debug_data_flow'):
    log_record['debug_data_flow'] = record.debug_data_flow
if hasattr(record, 'debug_component'):
    log_record['debug_component'] = record.debug_component

# В функцию setup_logging добавить поддержку DEBUG уровня:
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logger.setLevel(getattr(logging, log_level))

if log_level == "DEBUG":
    DEBUG_LOG_FILE = os.path.join(LOG_DIR, "debug.log")
    debug_handler = logging.FileHandler(DEBUG_LOG_FILE)
    debug_handler.setFormatter(JsonFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z"))
    debug_handler.setLevel(logging.DEBUG)
    logger.addHandler(debug_handler)
```

### 2. Middleware (src/api/middleware.py)

```python
# В методе dispatch добавить DEBUG логирование:
if logger.isEnabledFor(logging.DEBUG):
    request_body = None
    if request.method in ["POST", "PUT", "PATCH"]:
        try:
            request_body = await request.json()
        except:
            pass
            
    if request_body:
        logger.debug(
            "DEBUG: Incoming Request JSON",
            extra={
                "debug_json_data": request_body,
                "debug_data_flow": "incoming",
                "debug_component": "middleware",
                "request_id": request_id
            }
        )
```

### 3. Сервисы

#### ChatService (src/services/chat_service/chat_service.py)

```python
# После получения request_body:
if logger.isEnabledFor(logging.DEBUG):
    logger.debug(
        "DEBUG: Chat Completion Request JSON",
        extra={
            "debug_json_data": request_body,
            "debug_data_flow": "incoming",
            "debug_component": "chat_service",
            "request_id": request_id
        }
    )

# После получения ответа от провайдера:
if logger.isEnabledFor(logging.DEBUG):
    if isinstance(response_data, StreamingResponse):
        # Логируем первый chunk для примера
        first_chunk = None
        async for chunk in response_data.body_iterator:
            first_chunk = chunk.decode('utf-8')
            break
            
        logger.debug(
            "DEBUG: Streaming Response First Chunk",
            extra={
                "debug_json_data": {"chunk_preview": first_chunk},
                "debug_data_flow": "from_provider",
                "debug_component": "chat_service",
                "request_id": request_id
            }
        )
    else:
        logger.debug(
            "DEBUG: Chat Completion Response JSON",
            extra={
                "debug_json_data": response_data,
                "debug_data_flow": "from_provider",
                "debug_component": "chat_service",
                "request_id": request_id
            }
        )
```

#### EmbeddingService (src/services/embedding_service.py)

```python
# Аналогично ChatService, добавляем логирование запроса и ответа
if logger.isEnabledFor(logging.DEBUG):
    logger.debug(
        "DEBUG: Embedding Request JSON",
        extra={
            "debug_json_data": request_body,
            "debug_data_flow": "incoming",
            "debug_component": "embedding_service",
            "request_id": request_id
        }
    )

# После получения ответа:
if logger.isEnabledFor(logging.DEBUG):
    logger.debug(
        "DEBUG: Embedding Response JSON",
        extra={
            "debug_json_data": response_data,
            "debug_data_flow": "from_provider",
            "debug_component": "embedding_service",
            "request_id": request_id
        }
    )
```

#### TranscriptionService (src/services/transcription_service.py)

```python
# Логирование параметров запроса:
if logger.isEnabledFor(logging.DEBUG):
    debug_data = {
        "model_id": model_id,
        "response_format": response_format,
        "temperature": temperature,
        "language": language,
        "return_timestamps": return_timestamps,
        "filename": audio_file.filename,
        "content_type": audio_file.content_type,
        "file_size": audio_file.size if hasattr(audio_file, 'size') else None
    }
    logger.debug(
        "DEBUG: Transcription Request Parameters",
        extra={
            "debug_json_data": debug_data,
            "debug_data_flow": "incoming",
            "debug_component": "transcription_service",
            "request_id": request_id
        }
    )
```

### 4. Провайдеры

#### BaseProvider (src/providers/base.py)

```python
# В методе _stream_request:
if logger.isEnabledFor(logging.DEBUG):
    logger.debug(
        "DEBUG: Request to Provider",
        extra={
            "debug_json_data": {
                "url": f"{self.base_url}{url_path}",
                "headers": self.headers,
                "request_body": request_body
            },
            "debug_data_flow": "to_provider",
            "debug_component": "base_provider"
        }
    )
```

#### OpenAI Provider (src/providers/openai.py)

```python
# В методе chat_completions:
if logger.isEnabledFor(logging.DEBUG):
    debug_request = {
        "url": f"{self.base_url}/chat/completions",
        "headers": self.headers,
        "request_body": request_body,
        "provider_model_name": provider_model_name,
        "model_config": model_config
    }
    logger.debug(
        "DEBUG: OpenAI Chat Request",
        extra={
            "debug_json_data": debug_request,
            "debug_data_flow": "to_provider",
            "debug_component": "openai_provider"
        }
    )

# После получения ответа:
if logger.isEnabledFor(logging.DEBUG):
    logger.debug(
        "DEBUG: OpenAI Chat Response",
        extra={
            "debug_json_data": response_json,
            "debug_data_flow": "from_provider",
            "debug_component": "openai_provider"
        }
    )
```

## Шаблон для добавления DEBUG логирования

```python
# Стандартный шаблон для DEBUG логирования:
if logger.isEnabledFor(logging.DEBUG):
    logger.debug(
        "DEBUG: [Описание действия]",
        extra={
            "debug_json_data": [JSON данные без изменений],
            "debug_data_flow": "[incoming|outgoing|to_provider|from_provider]",
            "debug_component": "[имя компонента]",
            "request_id": request_id  # если доступно
        }
    )
```

## Значения debug_data_flow

- `incoming` - данные от клиента
- `outgoing` - данные к клиенту
- `to_provider` - данные к провайдеру
- `from_provider` - данные от провайдера

## Значения debug_component

- `middleware` - middleware слой
- `chat_service` - сервис чата
- `embedding_service` - сервис эмбеддингов
- `transcription_service` - сервис транскрипции
- `base_provider` - базовый провайдер
- `openai_provider` - OpenAI провайдер
- `anthropic_provider` - Anthropic провайдер
- `ollama_provider` - Ollama провайдер

## Включение DEBUG логирования

```bash
# Через переменную окружения
export LOG_LEVEL=DEBUG
python -m uvicorn src.api.main:app --reload

# Через Docker
docker compose up -d  # с LOG_LEVEL=DEBUG в environment
```

## Проверка работы

```bash
# Сделать запрос к сервису
curl -X POST "http://localhost:8777/v1/chat/completions" \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"model": "openai/gpt-4", "messages": [{"role": "user", "content": "Hello"}]}'

# Проверить DEBUG логи
tail -f logs/debug.log

# Поиск по request_id
grep "request_id\":\"your-request-id" logs/debug.log
```

## Важные моменты

1. **Всегда проверять** `logger.isEnabledFor(logging.DEBUG)` перед формированием DEBUG лога
2. **Логировать JSON как есть**, без изменений и фильтрации
3. **Использовать стандартный шаблон** для consistency
4. **Не логировать бинарные данные** (файлы в транскрипции)
5. **Для стриминга логировать только первый chunk** для примера

## Безопасность

⚠️ **ВНИМАНИЕ**: DEBUG логи содержат все данные включая чувствительную информацию. Использовать только в контролируемой среде.

## Отключение

```bash
# Отключить DEBUG логирование
export LOG_LEVEL=INFO
# или перезапустить сервис с другими настройками