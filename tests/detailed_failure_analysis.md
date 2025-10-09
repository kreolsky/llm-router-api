# Детальный анализ причин падений сервиса (500 ошибок)

## Обзор проблемы

Из 106 тестов в папке `tests/api/`:
- **90 passed** (84.9%)
- **15 failed** (14.2%)
- **1 skipped** (0.9%)

Основная проблема: сервис падает с ошибкой `500 Internal Server Error` вместо возврата корректных кодов состояния HTTP для предсказуемых ошибок валидации.

## Коренные причины 500 ошибок

### 1. Отсутствие валидации входных данных на уровне API

#### Проблема:
В эндпоинтах API отсутствует первичная валидация входных данных перед передачей их в сервисы. Это приводит к тому, что ошибки валидации доходят до уровня провайдеров и вызывают непредвиденные исключения.

#### Примеры в коде:

**Chat Completions (`src/api/main.py:70-75`)**:
```python
@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    auth_data: tuple = Depends(check_endpoint_access("/v1/chat/completions"))
):
    return await app.state.chat_service.chat_completions(request, auth_data)
```

**Embeddings (`src/api/main.py:77-82`)**:
```python
@app.post("/v1/embeddings")
async def create_embeddings(
    request: Request,
    auth_data: tuple = Depends(check_endpoint_access("/v1/embeddings"))
):
    return await app.state.embedding_service.create_embeddings(request, auth_data)
```

#### Проблема:
- Нет проверки наличия обязательных полей в запросе
- Нет базовой валидации формата данных
- Все ошибки обрабатываются только на уровне сервисов

### 2. Неполная обработка исключений в сервисах

#### Проблема:
В сервисах отсутствует обработка специфических исключений, связанных с валидацией данных, что приводит к их преобразованию в общие 500 ошибки.

#### Примеры в коде:

**Chat Service (`src/services/chat_service/chat_service.py:351-365`)**:
```python
except Exception as e:
    logger.error(
        f"Unexpected error in chat_completions: {e}",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "model_id": requested_model,
            "log_type": "error"
        },
        exc_info=True
    )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={"error": {"message": f"Internal server error: {e}", "code": "internal_server_error"}},
    )
```

**Embedding Service (`src/services/embedding_service.py:148-154`)**:
```python
except Exception as e:
    error_detail = {"error": {"message": f"An unexpected error occurred: {e}", "code": "unexpected_error"}}
    logger.error(f"An unexpected error occurred: {e}", extra={"detail": error_detail, "request_id": request_id, "user_id": user_id, "model_id": requested_model, "log_type": "error"}, exc_info=True)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=error_detail,
    )
```

#### Проблема:
- Все исключения обрабатываются как "неожиданные" и возвращают 500 ошибку
- Нет дифференциации между ошибками валидации и внутренними ошибками сервера

### 3. Отсутствие валидации на уровне провайдеров

#### Проблема:
Провайдеры не выполняют должную валидацию входных данных перед отправкой запросов внешним API.

#### Пример в коде:

**OpenAI Provider (`src/providers/openai.py:182-227`)**:
```python
async def embeddings(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
    # Transform request: Replace the model name with the provider's specific model name
    request_body["model"] = provider_model_name
    
    # Merge options from model_config into the request_body
    options = model_config.get("options")
    if options:
        request_body = deep_merge(request_body, options)

    try:
        # Отправка запроса без валидации request_body
        response = await self.client.post(f"{self.base_url}/embeddings",
                                         headers=self.headers,
                                         json=request_body,
                                         timeout=embeddings_timeout)
```

#### Проблема:
- Нет проверки наличия обязательных полей (например, `input` для эмбеддингов)
- Нет проверки формата данных перед отправкой внешнему API

### 4. Некорректная обработка ошибок от внешних API

#### Проблема:
Ошибки от внешних API (например, 422 Unprocessable Entity) не корректно обрабатываются и преобразуются в 500 ошибки.

#### Пример в коде:

**OpenAI Provider (`src/providers/openai.py:218-227`)**:
```python
except httpx.HTTPStatusError as e:
    raise HTTPException(
        status_code=e.response.status_code,
        detail={"error": {"message": f"Provider error: {e.response.text}", "code": f"provider_http_error_{e.response.status_code}"}},
    )
```

**Base Provider (`src/providers/base.py:93-98`)**:
```python
try:
    response.raise_for_status()
except httpx.HTTPStatusError as e:
    # Обработка ошибок, но не всегда корректная
    response_text = ""
    try:
        response_text = e.response.text
    except httpx.ResponseNotRead:
        response_text = "Unable to read error response from provider"
```

## Детальный анализ failing тестов

### 1. `test_chat_completion_missing_required_fields`
- **Ожидание**: 400 Bad Request
- **Фактический результат**: 422 Unprocessable Entity
- **Причина**: Внешний API возвращает 422, но сервис не преобразует его в 400

### 2. `test_chat_completion_empty_messages`
- **Ожидание**: 400 Bad Request  
- **Фактический результат**: 200 OK (тест проходит, но не должен)
- **Причина**: Отсутствует валидация пустого массива сообщений

### 3. `test_create_embeddings_missing_required_fields`
- **Ожидание**: 400 Bad Request
- **Фактический результат**: 422 Unprocessable Entity
- **Причина**: Внешний API возвращает 422, но сервис не преобразует его в 400

### 4. `test_create_embeddings_empty_input`
- **Ожидание**: 400 Bad Request
- **Фактический результат**: 500 Internal Server Error
- **Причина**: Провайдер падает при обработке пустого input без проверки

### 5. `test_create_transcription_missing_required_fields`
- **Ожидание**: 400 Bad Request
- **Фактический результат**: 500 Internal Server Error
- **Причина**: Отсутствует валидация наличия файла и модели в эндпоинте

### 6. `test_create_transcription_empty_file`
- **Ожидание**: 400 Bad Request
- **Фактический результат**: 500 Internal Server Error
- **Причина**: Провайдер падает при обработке пустого файла без проверки

### 7. `test_create_transcription_large_file`
- **Ожидание**: [200, 400, 413]
- **Фактический результат**: 500 Internal Server Error
- **Причина**: Провайдер падает при обработке большого файла без проверки размера

## Архитектурные проблемы

### 1. Отсутствие слоя валидации
В архитектуре отсутствует выделенный слой валидации входных данных. Валидация происходит только на уровне внешних API, что приводит к неправильным кодам состояния.

### 2. Неправильная обработка ошибок валидации
Ошибки валидации (4xx) от внешних API не преобразуются в соответствующие ошибки клиентского API, а возвращаются как есть или превращаются в 500 ошибки.

### 3. Отсутствие централизованной обработки ошибок
Каждый сервис и провайдер обрабатывают ошибки по-своему, что приводит к несогласованности в кодах состояния и форматах ответов.

### 4. Низкая информативность ошибок
Сообщения об ошибках не всегда содержат достаточно информации для понимания причины проблемы, что затрудняет отладку.

## Последствия

1. **Плохой пользовательский опыт**: Клиенты получают 500 ошибки вместо понятных ошибок валидации
2. **Сложности в отладке**: Разработчикам сложно определить причину проблем
3. **Несоответствие REST принципам**: Неправильные коды состояния HTTP
4. **Нестабильность сервиса**: Базовые ошибки валидации приводят к падениям запросов

## Заключение

Основная проблема 500 ошибок заключается в отсутствии должной валидации входных данных на всех уровнях архитектуры и неправильной обработке ошибок от внешних API. Для решения проблемы необходимо внедрить комплексный подход к валидации данных и обработке ошибок на всех уровнях приложения.