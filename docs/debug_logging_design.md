# Архитектура DEBUG логирования для NNp LLM Router

## Обзор

Документ описывает архитектуру и реализацию системы DEBUG логирования для NNp LLM Router, которая обеспечивает полное логирование всех JSON-данных, проходящих через сервис. Это необходимо для отлова редкого бага, требующего полного просмотра всех данных.

## Требования

1. **Полное логирование JSON-данных**: Все JSON-данные, поступающие от клиента, к провайдерам и от провайдеров, должны логироваться без изменений
2. **Без изменений данных**: Логирование должно происходить без какой-либо обработки или фильтрации данных
3. **Конфигурируемость**: Возможность включения/выключения DEBUG логирования через конфигурацию
4. **Изолированность**: DEBUG логирование должно работать параллельно с существующим INFO/ERROR логированием
5. **Производительность**: Минимальное влияние на производительность в обычном режиме (когда DEBUG отключен)

## Архитектура

### 1. Расширение системы логирования

#### Модификация JsonFormatter

```python
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        
        # Существующие поля для INFO/ERROR логов...
        
        # Новые поля для DEBUG логов
        if hasattr(record, 'debug_json_data'):
            log_record['debug_json_data'] = record.debug_json_data
        if hasattr(record, 'debug_data_flow'):
            log_record['debug_data_flow'] = record.debug_data_flow  # 'incoming', 'outgoing', 'to_provider', 'from_provider'
        if hasattr(record, 'debug_component'):
            log_record['debug_component'] = record.debug_component  # 'middleware', 'chat_service', 'provider', etc.
            
        return json.dumps(log_record, ensure_ascii=False)
```

#### Модификация setup_logging()

```python
def setup_logging():
    # Получаем уровень логирования из переменной окружения
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    
    logger = logging.getLogger("nnp-llm-router")
    logger.setLevel(getattr(logging, log_level))
    
    # Для DEBUG режима создаем отдельный файл
    if log_level == "DEBUG":
        DEBUG_LOG_FILE = os.path.join(LOG_DIR, "debug.log")
        debug_handler = logging.FileHandler(DEBUG_LOG_FILE)
        debug_handler.setFormatter(JsonFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z"))
        debug_handler.setLevel(logging.DEBUG)
        logger.addHandler(debug_handler)
```

### 2. Точки логирования

#### 2.1 Middleware (`src/api/middleware.py`)

```python
class RequestLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = os.urandom(8).hex()
        request.state.request_id = request_id
        
        # DEBUG логирование входящего запроса
        if logger.isEnabledFor(logging.DEBUG):
            request_body = None
            if request.method in ["POST", "PUT", "PATCH"]:
                try:
                    request_body = await request.json()
                except:
                    pass  # Если не JSON, пропускаем
                    
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
        
        # ... существующая логика ...
        
        # DEBUG логирование исходящего ответа
        if logger.isEnabledFor(logging.DEBUG) and hasattr(response, 'body'):
            try:
                response_body = json.loads(response.body)
                logger.debug(
                    "DEBUG: Outgoing Response JSON",
                    extra={
                        "debug_json_data": response_body,
                        "debug_data_flow": "outgoing",
                        "debug_component": "middleware",
                        "request_id": request_id
                    }
                )
            except:
                pass  # Если не JSON, пропускаем
```

#### 2.2 ChatService (`src/services/chat_service/chat_service.py`)

```python
async def chat_completions(self, request: Request, auth_data: Tuple[str, str, list, list]) -> Any:
    project_name, api_key, allowed_models, _ = auth_data
    request_id = request.state.request_id
    
    request_body = await request.json()
    
    # DEBUG логирование полного запроса
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
    
    # ... существующая логика ...
    
    try:
        response_data = await provider_instance.chat_completions(request_body, provider_model_name, model_config)
        
        # DEBUG логирование ответа от провайдера
        if logger.isEnabledFor(logging.DEBUG):
            if isinstance(response_data, StreamingResponse):
                # Для стриминга логируем первый chunk для примера
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
                # Для нестриминговых ответов логируем полный JSON
                logger.debug(
                    "DEBUG: Chat Completion Response JSON",
                    extra={
                        "debug_json_data": response_data,
                        "debug_data_flow": "from_provider",
                        "debug_component": "chat_service",
                        "request_id": request_id
                    }
                )
        
        return response_data
```

#### 2.3 EmbeddingService (`src/services/embedding_service.py`)

```python
async def create_embeddings(self, request: Request, auth_data: Tuple[str, str, list, list]) -> Any:
    # ... существующая логика ...
    
    request_body = await request.json()
    
    # DEBUG логирование
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
    
    # ... обработка ...
    
    response_data = await provider_instance.embeddings(request_body, provider_model_name, model_config)
    
    # DEBUG логирование ответа
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

#### 2.4 TranscriptionService (`src/services/transcription_service.py`)

```python
async def create_transcription(self, audio_file: UploadFile, model_id: Optional[str] = None, auth_data: Tuple[str, str, Any, Any] = None, ...):
    # DEBUG логирование параметров запроса
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
                "request_id": getattr(request.state, 'request_id', 'unknown') if 'request' in locals() else 'unknown'
            }
        )
    
    # ... обработка ...
    
    response = await provider_instance.transcriptions(...)
    
    # DEBUG логирование ответа
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "DEBUG: Transcription Response JSON",
            extra={
                "debug_json_data": response,
                "debug_data_flow": "from_provider",
                "debug_component": "transcription_service",
                "request_id": getattr(request.state, 'request_id', 'unknown') if 'request' in locals() else 'unknown'
            }
        )
```

#### 2.5 BaseProvider (`src/providers/base.py`)

```python
@retry_on_rate_limit(max_retries=3, base_delay=1.0, max_delay=30.0)
async def _stream_request(self, client: httpx.AsyncClient, url_path: str, request_body: Dict[str, Any]) -> StreamingResponse:
    # DEBUG логирование запроса к провайдеру
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
    
    # ... существующая логика ...
    
    async def generate():
        async with client.stream("POST", f"{self.base_url}{url_path}",
                                 headers=self.headers,
                                 json=request_body,
                                 timeout=stream_timeout) as response:
            
            # DEBUG логирование заголовков ответа
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "DEBUG: Provider Response Headers",
                    extra={
                        "debug_json_data": {
                            "status_code": response.status_code,
                            "headers": dict(response.headers)
                        },
                        "debug_data_flow": "from_provider",
                        "debug_component": "base_provider"
                    }
                )
            
            # ... существующая логика ...
```

#### 2.6 OpenAI Provider (`src/providers/openai.py`)

```python
async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
    # DEBUG логирование запроса к провайдеру
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
    
    # ... существующая логика ...
    
    if not stream:
        response = await self.client.post(...)
        response_json = response.json()
        
        # DEBUG логирование ответа от провайдера
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "DEBUG: OpenAI Chat Response",
                extra={
                    "debug_json_data": response_json,
                    "debug_data_flow": "from_provider",
                    "debug_component": "openai_provider"
                }
            )
        
        return response_json
```

### 3. Конфигурация

#### 3.1 Переменные окружения

```bash
# Включение DEBUG логирования
LOG_LEVEL=DEBUG

# Опционально: отдельный файл для DEBUG логов
DEBUG_LOG_FILE=logs/debug.log
```

#### 3.2 Docker Compose

```yaml
services:
  api:
    environment:
      - LOG_LEVEL=DEBUG  # Изменить на INFO для продакшена
    volumes:
      - ./logs:/app/logs  # Для сохранения логов
```

### 4. Формат DEBUG логов

#### 4.1 Структура JSON лога

```json
{
  "timestamp": "2025-01-01T12:00:00+0000",
  "level": "DEBUG",
  "message": "DEBUG: Chat Completion Request JSON",
  "debug_json_data": {
    "model": "openai/gpt-4",
    "messages": [
      {"role": "user", "content": "Hello"}
    ],
    "temperature": 0.7,
    "max_tokens": 1000
  },
  "debug_data_flow": "incoming",
  "debug_component": "chat_service",
  "request_id": "a1b2c3d4e5f6"
}
```

#### 4.2 Типы data_flow

- `incoming` - данные от клиента
- `outgoing` - данные к клиенту
- `to_provider` - данные к провайдеру
- `from_provider` - данные от провайдера

#### 4.3 Компоненты

- `middleware` - middleware слой
- `chat_service` - сервис чата
- `embedding_service` - сервис эмбеддингов
- `transcription_service` - сервис транскрипции
- `base_provider` - базовый провайдер
- `openai_provider` - OpenAI провайдер
- `anthropic_provider` - Anthropic провайдер
- `ollama_provider` - Ollama провайдер

### 5. Использование

#### 5.1 Включение DEBUG логирования

```bash
# Для разработки
export LOG_LEVEL=DEBUG
python -m uvicorn src.api.main:app --reload

# Для Docker
docker compose up -d
# или с переопределением
docker compose -f docker-compose.yml --env-file .env.debug up
```

#### 5.2 Просмотр логов

```bash
# Просмотр всех логов
tail -f logs/app.log

# Только DEBUG логи
tail -f logs/debug.log

# Фильтрация по request_id
grep "request_id\":\"a1b2c3d4e5f6" logs/debug.log

# Фильтрация по компоненту
grep "debug_component\":\"chat_service" logs/debug.log
```

#### 5.3 Анализ логов

```bash
# Поиск полного запроса по request_id
grep -A 10 -B 10 "request_id\":\"a1b2c3d4e5f6" logs/debug.log

# Построение цепочки запроса
grep "request_id\":\"a1b2c3d4e5f6" logs/debug.log | jq '.debug_data_flow, .debug_component'
```

### 6. Производительность

#### 6.1 Оптимизации

1. **Ленивое логирование**: Проверка `logger.isEnabledFor(logging.DEBUG)` перед формированием лога
2. **Отдельный файл**: DEBUG логи пишутся в отдельный файл для минимизации влияния на основные логи
3. **Асинхронная запись**: Использование асинхронных хендлеров при необходимости
4. **Ограничение размера**: Ротация логов для предотвращения переполнения диска

#### 6.2 Мониторинг производительности

```python
# В middleware можно добавить метрики производительности
if logger.isEnabledFor(logging.DEBUG):
    start_time = time.time()
    # ... обработка запроса ...
    end_time = time.time()
    logger.debug(
        "DEBUG: Request Processing Time",
        extra={
            "debug_json_data": {
                "processing_time_ms": (end_time - start_time) * 1000,
                "request_size_bytes": len(str(request_body))
            },
            "debug_data_flow": "internal",
            "debug_component": "middleware"
        }
    )
```

### 7. Безопасность

#### 7.1 Учетные данные

В DEBUG логах могут содержаться чувствительные данные:
- API ключи
- Содержимое сообщений пользователей
- Конфигурационные данные

**Важно**: DEBUG логи должны использоваться только в контролируемой среде разработки или для локального отладки, как указано в требованиях.

#### 7.2 Рекомендации

1. **Не использовать в продакшене**: Всегда устанавливать LOG_LEVEL=INFO или выше
2. **Ограничить доступ**: Файлы DEBUG логов должны иметь ограниченные права доступа
3. **Чистка**: Регулярно удалять старые DEBUG логи
4. **Фильтрация**: При необходимости можно добавить фильтрацию чувствительных полей

### 8. План реализации

1. **Модификация системы логирования** - расширение JsonFormatter и setup_logging
2. **Добавление DEBUG логов в middleware** - полное логирование запросов/ответов
3. **Добавление DEBUG логов в сервисы** - ChatService, EmbeddingService, TranscriptionService
4. **Добавление DEBUG логов в провайдеры** - BaseProvider и конкретные реализации
5. **Тестирование** - проверка работы во всех сценариях
6. **Документация** - создание инструкции по использованию

### 9. Тестирование

#### 9.1 Unit тесты

```python
def test_debug_logging_enabled():
    # Проверка, что DEBUG логи пишутся при LOG_LEVEL=DEBUG
    pass

def test_debug_logging_disabled():
    # Проверка, что DEBUG логи не пишутся при LOG_LEVEL=INFO
    pass
```

#### 9.2 Интеграционные тесты

```python
async def test_full_request_debug_flow():
    # Проверка полного цикла логирования для запроса
    pass
```

### 10. Заключение

Предложенная архитектура обеспечивает полное логирование всех JSON-данных, проходящих через сервис, что позволит эффективно отлавливать редкие баги. Система спроектирована с учетом требований производительности и безопасности.