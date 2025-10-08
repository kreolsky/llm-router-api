# Исправление проблемы с "съеданием" первого токена в стриминге

## Проблема

При включении DEBUG логирования первый chunk стримингового ответа "съедается" для логирования и не доходит до клиента. Это происходит в файле `src/services/chat_service/chat_service.py` в строках 260-264:

```python
# Для стриминга логируем первый chunk для примера
first_chunk = None
async for chunk in response_data.body_iterator:
    first_chunk = chunk.decode('utf-8')
    break  # <-- Проблема: мы выходим из цикла после первого chunk
```

## Решение

Нужно создать новый итератор, который будет возвращать chunks без "съедания" первого. Для этого можно использовать `itertools.chain` или создать специальный генератор.

### Вариант 1: Использование itertools.chain

```python
import itertools

# В методе chat_completions:
if isinstance(response_data, StreamingResponse):
    # Создаем копию итератора для логирования
    chunks_iter = response_data.body_iterator
    chunks_iter_copy, chunks_iter = itertools.tee(chunks_iter)
    
    # Логируем первый chunk для примера
    first_chunk = None
    async for chunk in chunks_iter_copy:
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
    
    # Используем оригинальный итератор для основного потока
    return StreamingResponse(
        self.stream_processor.process_stream(
            chunks_iter, requested_model, request_id, user_id
        ),
        media_type=response_data.media_type
    )
```

### Вариант 2: Создание специального генератора

```python
async def stream_with_logging(stream_iterator, request_id):
    """Генератор, который логирует первый chunk и передает все chunks дальше"""
    first_chunk_logged = False
    
    async for chunk in stream_iterator:
        if not first_chunk_logged and logger.isEnabledFor(logging.DEBUG):
            first_chunk = chunk.decode('utf-8')
            logger.debug(
                "DEBUG: Streaming Response First Chunk",
                extra={
                    "debug_json_data": {"chunk_preview": first_chunk},
                    "debug_data_flow": "from_provider",
                    "debug_component": "chat_service",
                    "request_id": request_id
                }
            )
            first_chunk_logged = True
        
        yield chunk

# В методе chat_completions:
if isinstance(response_data, StreamingResponse):
    # Используем специальный генератор
    return StreamingResponse(
        self.stream_processor.process_stream(
            stream_with_logging(response_data.body_iterator, request_id),
            requested_model, request_id, user_id
        ),
        media_type=response_data.media_type
    )
```

### Вариант 3: Упрощенный подход (рекомендуемый)

```python
# В методе chat_completions:
if isinstance(response_data, StreamingResponse):
    # Для стриминга не логируем первый chunk, чтобы не "съедать" его
    # Вместо этого можно логировать метаданные запроса
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "DEBUG: Streaming Response Started",
            extra={
                "debug_json_data": {
                    "streaming": True,
                    "model": requested_model,
                    "request_id": request_id
                },
                "debug_data_flow": "from_provider",
                "debug_component": "chat_service",
                "request_id": request_id
            }
        )
    
    # Используем оригинальный итератор без изменений
    return StreamingResponse(
        self.stream_processor.process_stream(
            response_data.body_iterator, requested_model, request_id, user_id
        ),
        media_type=response_data.media_type
    )
```

## Рекомендация

Использовать **Вариант 3** как самый простой и надежный. Он полностью решает проблему "съедания" первого chunk, сохраняя при этом возможность DEBUG логирования метаданных стримингового запроса.

Если все же необходимо логировать содержимое первого chunk, то **Вариант 2** является предпочтительным, так как он не требует дополнительных библиотек и более понятен в реализации.