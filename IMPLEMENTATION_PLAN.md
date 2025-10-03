# 🚀 План реализации исправлений LLM Router

## 📋 Обзор

Этот документ содержит пошаговый план исправления критических проблем, выявленных в аудите. План разделен на 3 этапа по приоритету.

---

## 🔴 Этап 1: Критические исправления (СРОЧНО)

### Задача 1.1: Исправить разрыв UTF-8 символов
**Файл:** `src/services/chat_service.py`  
**Приоритет:** 🔴 КРИТИЧНО  
**Время:** 2-3 часа

#### Изменения:

```python
# В начале класса ChatService добавить:
import codecs

# В методе _stream_response_handler (строка 156):
async def _stream_response_handler(self, response_data: StreamingResponse, provider_type: str, requested_model: str, request_id: str, user_id: str):
    full_content = ""
    stream_completed_usage = None
    
    # ✅ ДОБАВИТЬ: Создать инкрементальный декодер
    utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='ignore')
    
    try:
        async for chunk in response_data.body_iterator:
            try:
                # ✅ ИЗМЕНИТЬ: Использовать инкрементальный декодер
                decoded_chunk = utf8_decoder.decode(chunk, final=False)
                
                # Если decoded_chunk пустой, значит chunk был частью многобайтного символа
                if not decoded_chunk:
                    continue
                
                # ... остальной код без изменений
```

#### Тестирование:
```bash
# Тест с emoji и кириллицей
curl -X POST http://localhost:8777/v1/chat/completions \
  -H "Authorization: Bearer dummy" \
  -d '{
    "model": "deepseek/chat",
    "messages": [{"role": "user", "content": "Ответь на русском с emoji: расскажи про Python 🐍"}],
    "stream": true
  }'
```

---

### Задача 1.2: Добавить буферизацию для SSE событий
**Файл:** `src/services/chat_service.py`  
**Приоритет:** 🔴 КРИТИЧНО  
**Время:** 3-4 часа

#### Изменения:

```python
async def _stream_response_handler(self, response_data: StreamingResponse, provider_type: str, requested_model: str, request_id: str, user_id: str):
    full_content = ""
    stream_completed_usage = None
    utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='ignore')
    
    # ✅ ДОБАВИТЬ: Буфер для неполных SSE строк
    sse_buffer = ""
    json_buffer = ""
    
    try:
        async for chunk in response_data.body_iterator:
            try:
                decoded_chunk = utf8_decoder.decode(chunk, final=False)
                if not decoded_chunk:
                    continue
                
                # ✅ ДОБАВИТЬ: Обработка в зависимости от типа провайдера
                if provider_type == "ollama":
                    # Буферизация NDJSON
                    json_buffer += decoded_chunk
                    lines = json_buffer.split('\n')
                    json_buffer = lines[-1]  # Сохранить неполную строку
                    
                    for line in lines[:-1]:
                        if line.strip():
                            processed_chunk, full_content, stream_completed_usage = \
                                self._process_ollama_line(line, full_content, stream_completed_usage, requested_model, request_id, user_id)
                            if processed_chunk:
                                yield processed_chunk
                else:
                    # Буферизация SSE
                    sse_buffer += decoded_chunk
                    
                    # SSE события разделены двойным \n\n
                    while '\n\n' in sse_buffer:
                        event, sse_buffer = sse_buffer.split('\n\n', 1)
                        if event.strip():
                            full_content, stream_completed_usage = \
                                self._process_openai_sse_event(event, full_content, stream_completed_usage, request_id, user_id)
                            # Отправляем с правильным форматированием SSE
                            yield f"{event}\n\n".encode('utf-8')
                            
            except json.JSONDecodeError as e:
                logger.error(f"JSONDecodeError in stream for request {request_id}: {e}. Malformed chunk received.", 
                           extra={"request_id": request_id, "user_id": user_id, "log_type": "error", "exception": str(e)})
                yield self._format_sse_error(f"Malformed JSON received from provider: {e}", "malformed_json", status.HTTP_502_BAD_GATEWAY)
                break
            # ... остальные except блоки
                
    except Exception as e:
        logger.error(f"Critical error before stream iteration for request {request_id}: {e}", 
                   extra={"request_id": request_id, "user_id": user_id, "log_type": "error", "exception": str(e)}, exc_info=True)
        yield self._format_sse_error(f"A critical error occurred before streaming: {e}", "critical_streaming_error", status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ✅ ДОБАВИТЬ: Обработать остатки в буферах
    if sse_buffer.strip():
        full_content, stream_completed_usage = self._process_openai_sse_event(sse_buffer, full_content, stream_completed_usage, request_id, user_id)
    if json_buffer.strip():
        try:
            self._process_ollama_line(json_buffer, full_content, stream_completed_usage, requested_model, request_id, user_id)
        except:
            pass
    
    self._log_streaming_completion(request_id, user_id, requested_model, full_content, stream_completed_usage)
    yield b"data: [DONE]\n\n"
```

#### Новые методы:

```python
def _process_openai_sse_event(self, event: str, full_content: str, stream_completed_usage: Dict[str, Any], request_id: str, user_id: str) -> Tuple[str, Dict[str, Any]]:
    """Обрабатывает одно SSE событие (может содержать несколько data: строк)"""
    for line in event.split('\n'):
        if line.startswith('data: '):
            json_data = line[6:].strip()  # Убрать 'data: '
            if json_data == '[DONE]':
                continue
            try:
                data = json.loads(json_data)
                if 'choices' in data and len(data['choices']) > 0:
                    delta_content = data['choices'][0].get('delta', {}).get('content')
                    if delta_content:
                        full_content += delta_content
                if 'usage' in data:
                    stream_completed_usage = data['usage']
            except json.JSONDecodeError as e:
                raise e
    return full_content, stream_completed_usage

def _process_ollama_line(self, line: str, full_content: str, stream_completed_usage: Dict[str, Any], requested_model: str, request_id: str, user_id: str) -> Tuple[bytes, str, Dict[str, Any]]:
    """Обрабатывает одну строку NDJSON от Ollama"""
    processed_chunk = b""
    try:
        data = json.loads(line)
        if data.get('done'):
            if 'prompt_eval_count' in data:
                stream_completed_usage = {
                    "prompt_tokens": data.get("prompt_eval_count", 0),
                    "completion_tokens": data.get("eval_count", 0)
                }
            elif 'usage' in data:
                stream_completed_usage = data['usage']
            return processed_chunk, full_content, stream_completed_usage
        
        delta_content = data.get('message', {}).get('content', '')
        if delta_content:
            full_content += delta_content
        
        openai_chunk = {
            "id": f"chatcmpl-{request_id}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": requested_model,
            "choices": [{
                "index": 0,
                "delta": {"content": delta_content},
                "logprobs": None,
                "finish_reason": None
            }]
        }
        processed_chunk = f"data: {json.dumps(openai_chunk)}\n\n".encode('utf-8')
    except json.JSONDecodeError as e:
        raise e
    return processed_chunk, full_content, stream_completed_usage
```

---

### Задача 1.3: Исправить обработку ошибок в стриме
**Файл:** `src/services/chat_service.py`  
**Приоритет:** 🔴 КРИТИЧНО  
**Время:** 1-2 часа

#### Изменения:

```python
async def _stream_response_handler(self, response_data: StreamingResponse, provider_type: str, requested_model: str, request_id: str, user_id: str):
    full_content = ""
    stream_completed_usage = None
    utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='ignore')
    sse_buffer = ""
    json_buffer = ""
    
    # ✅ ДОБАВИТЬ: Флаг ошибки
    stream_has_error = False
    
    try:
        async for chunk in response_data.body_iterator:
            try:
                # ... обработка чанков
            except json.JSONDecodeError as e:
                logger.error(f"JSONDecodeError in stream for request {request_id}: {e}", ...)
                yield self._format_sse_error(f"Malformed JSON: {e}", "malformed_json", status.HTTP_502_BAD_GATEWAY)
                stream_has_error = True  # ✅ ДОБАВИТЬ
                break
            except ProviderStreamError as e:
                logger.error(f"ProviderStreamError in stream for request {request_id}: {e.message}", ...)
                yield self._format_sse_error(e.message, e.error_code, e.status_code)
                stream_has_error = True  # ✅ ДОБАВИТЬ
                break
            except ProviderNetworkError as e:
                logger.error(f"ProviderNetworkError in stream for request {request_id}: {e.message}", ...)
                yield self._format_sse_error(e.message, "provider_network_error", status.HTTP_503_SERVICE_UNAVAILABLE)
                stream_has_error = True  # ✅ ДОБАВИТЬ
                break
            except Exception as e:
                logger.error(f"Unexpected error in stream for request {request_id}: {e}", ...)
                yield self._format_sse_error(f"Unexpected error: {e}", "unexpected_streaming_error", status.HTTP_500_INTERNAL_SERVER_ERROR)
                stream_has_error = True  # ✅ ДОБАВИТЬ
                break
                
    except Exception as e:
        logger.error(f"Critical error before stream iteration for request {request_id}: {e}", ...)
        yield self._format_sse_error(f"Critical error: {e}", "critical_streaming_error", status.HTTP_500_INTERNAL_SERVER_ERROR)
        stream_has_error = True  # ✅ ДОБАВИТЬ

    # ✅ ИЗМЕНИТЬ: Отправлять [DONE] только если не было ошибок
    if not stream_has_error:
        # Обработать остатки буферов
        # ...
        self._log_streaming_completion(request_id, user_id, requested_model, full_content, stream_completed_usage)
        yield b"data: [DONE]\n\n"
    else:
        logger.warning(f"Stream terminated with error for request {request_id}, skipping [DONE]", 
                     extra={"request_id": request_id, "user_id": user_id, "log_type": "warning"})
```

---

### Задача 1.4: Улучшить формат ошибок для OpenAI совместимости
**Файл:** `src/services/chat_service.py`  
**Приоритет:** 🔴 КРИТИЧНО  
**Время:** 1 час

#### Изменения:

```python
def _format_sse_error(self, message: str, code: str, status_code: int) -> bytes:
    """
    Форматирует ошибку в SSE формате, совместимом с OpenAI API.
    OpenAI отправляет ошибки как отдельное SSE событие, не как chunk.
    """
    # ✅ ИЗМЕНИТЬ: Использовать стандартный формат ошибок OpenAI
    error_payload = {
        "error": {
            "message": message,
            "type": "api_error",
            "code": code,
            "param": None
        }
    }
    
    # Отправляем как data: с объектом error
    return f"data: {json.dumps(error_payload)}\n\n".encode('utf-8')
```

---

## 🟡 Этап 2: Улучшение стабильности (ВАЖНО)

### Задача 2.1: Автоматическое определение формата стрима
**Файл:** `src/services/chat_service.py`  
**Приоритет:** 🟡 ВАЖНО  
**Время:** 2-3 часа

#### Изменения:

```python
async def _stream_response_handler(self, response_data: StreamingResponse, provider_type: str, requested_model: str, request_id: str, user_id: str):
    # ... инициализация
    
    # ✅ ДОБАВИТЬ: Автоопределение формата
    stream_format = None  # 'sse' или 'ndjson'
    first_chunk = True
    
    try:
        async for chunk in response_data.body_iterator:
            try:
                decoded_chunk = utf8_decoder.decode(chunk, final=False)
                if not decoded_chunk:
                    continue
                
                # ✅ ДОБАВИТЬ: Определить формат по первому чанку
                if first_chunk:
                    first_chunk = False
                    if 'data:' in decoded_chunk or decoded_chunk.startswith(':'):
                        stream_format = 'sse'
                        logger.info(f"Detected SSE format for request {request_id}", 
                                  extra={"request_id": request_id, "provider_type": provider_type})
                    else:
                        stream_format = 'ndjson'
                        logger.info(f"Detected NDJSON format for request {request_id}", 
                                  extra={"request_id": request_id, "provider_type": provider_type})
                
                # ✅ ИЗМЕНИТЬ: Использовать определенный формат вместо provider_type
                if stream_format == 'ndjson':
                    # NDJSON обработка
                    json_buffer += decoded_chunk
                    # ...
                elif stream_format == 'sse':
                    # SSE обработка
                    sse_buffer += decoded_chunk
                    # ...
                else:
                    # Fallback: пропустить чанк как есть
                    yield chunk
```

---

### Задача 2.2: Расширенная валидация SSE формата
**Файл:** `src/services/chat_service.py`  
**Приоритет:** 🟡 ВАЖНО  
**Время:** 2 часа

#### Изменения:

```python
def _process_openai_sse_event(self, event: str, full_content: str, stream_completed_usage: Dict[str, Any], request_id: str, user_id: str) -> Tuple[str, Dict[str, Any]]:
    """Обрабатывает SSE событие с поддержкой всех SSE конструкций"""
    
    event_type = None
    event_data_lines = []
    
    for line in event.split('\n'):
        line = line.strip()
        
        # ✅ ДОБАВИТЬ: Обработка SSE комментариев
        if line.startswith(':'):
            continue  # Игнорируем комментарии
        
        # ✅ ДОБАВИТЬ: Обработка event: поля
        if line.startswith('event: '):
            event_type = line[7:].strip()
            continue
        
        # Обработка data: поля
        if line.startswith('data: '):
            data_content = line[6:].strip()
            event_data_lines.append(data_content)
    
    # ✅ ДОБАВИТЬ: Обработка по типу события
    if event_type == 'error':
        # Специальная обработка ошибок
        logger.warning(f"Received error event in SSE stream for request {request_id}", 
                     extra={"request_id": request_id, "event_data": event_data_lines})
        return full_content, stream_completed_usage
    
    # Обработка data
    for json_data in event_data_lines:
        if json_data == '[DONE]':
            continue
        try:
            data = json.loads(json_data)
            
            # ✅ ДОБАВИТЬ: Обработка ошибок в data
            if 'error' in data:
                logger.error(f"Error in SSE data for request {request_id}: {data['error']}", 
                           extra={"request_id": request_id, "error_data": data['error']})
                continue
            
            if 'choices' in data and len(data['choices']) > 0:
                delta_content = data['choices'][0].get('delta', {}).get('content')
                if delta_content:
                    full_content += delta_content
            if 'usage' in data:
                stream_completed_usage = data['usage']
        except json.JSONDecodeError as e:
            raise e
    
    return full_content, stream_completed_usage
```

---

### Задача 2.3: Настройка таймаутов
**Файлы:** `src/providers/base.py`, `src/providers/openai.py`, `src/providers/ollama.py`  
**Приоритет:** 🟡 ВАЖНО  
**Время:** 1-2 часа

#### Изменения в `src/providers/base.py`:

```python
async def _stream_request(self, client: httpx.AsyncClient, url_path: str, request_body: Dict[str, Any]) -> StreamingResponse:
    async def generate():
        # ✅ ИЗМЕНИТЬ: Динамический таймаут для стриминга
        stream_timeout = httpx.Timeout(
            connect=10.0,   # Подключение: 10 сек
            read=30.0,      # Чтение чанка: 30 сек (между чанками)
            write=10.0,     # Запись: 10 сек
            pool=10.0       # Pool: 10 сек
        )
        
        async with client.stream("POST", f"{self.base_url}{url_path}", 
                                 headers=self.headers, 
                                 json=request_body,
                                 timeout=stream_timeout) as response:  # ✅ ИЗМЕНИТЬ
            # ... остальной код
```

#### Изменения в `src/providers/openai.py`:

```python
async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
    request_body["model"] = provider_model_name
    options = model_config.get("options")
    if options:
        request_body = deep_merge(request_body, options)

    stream = request_body.get("stream", False)

    try:
        if stream:
            return await self._stream_request(self.client, "/chat/completions", request_body)
        else:
            # ✅ ИЗМЕНИТЬ: Меньший таймаут для non-streaming
            non_stream_timeout = httpx.Timeout(
                connect=10.0,
                read=60.0,    # 1 минута для полного ответа
                write=10.0,
                pool=10.0
            )
            
            response = await self.client.post(
                f"{self.base_url}/chat/completions", 
                headers=self.headers, 
                json=request_body,
                timeout=non_stream_timeout  # ✅ ИЗМЕНИТЬ
            )
            response.raise_for_status()
            return response.json()
```

---

## 🟢 Этап 3: Архитектурные улучшения (ОПЦИОНАЛЬНО)

### Задача 3.1: Backpressure механизм
**Файл:** `src/services/chat_service.py`  
**Приоритет:** 🟢 ЖЕЛАТЕЛЬНО  
**Время:** 4-6 часов

#### Концепция:

```python
import asyncio

async def _stream_response_handler(self, response_data: StreamingResponse, provider_type: str, requested_model: str, request_id: str, user_id: str):
    # ✅ ДОБАВИТЬ: Очередь для backpressure
    chunk_queue = asyncio.Queue(maxsize=10)  # Макс 10 чанков в буфере
    
    async def producer():
        """Читает чанки от провайдера"""
        async for chunk in response_data.body_iterator:
            await chunk_queue.put(chunk)
        await chunk_queue.put(None)  # Сигнал окончания
    
    async def consumer():
        """Обрабатывает и отправляет чанки клиенту"""
        while True:
            chunk = await chunk_queue.get()
            if chunk is None:
                break
            # Обработка чанка
            yield processed_chunk
    
    # Запустить producer в фоне
    producer_task = asyncio.create_task(producer())
    
    try:
        async for chunk in consumer():
            yield chunk
    finally:
        producer_task.cancel()
```

---

### Задача 3.2: Метрики и мониторинг
**Файл:** `src/services/chat_service.py`  
**Приоритет:** 🟢 ЖЕЛАТЕЛЬНО  
**Время:** 3-4 часа

#### Концепция:

```python
from dataclasses import dataclass, field
from typing import List

@dataclass
class StreamMetrics:
    request_id: str
    chunks_processed: int = 0
    chunks_failed: int = 0
    bytes_received: int = 0
    unicode_errors: int = 0
    json_errors: int = 0
    start_time: float = field(default_factory=time.time)
    end_time: float = None
    
    def finalize(self):
        self.end_time = time.time()
    
    def duration(self) -> float:
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time
    
    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "chunks_processed": self.chunks_processed,
            "chunks_failed": self.chunks_failed,
            "bytes_received": self.bytes_received,
            "unicode_errors": self.unicode_errors,
            "json_errors": self.json_errors,
            "duration": self.duration()
        }

async def _stream_response_handler(...):
    metrics = StreamMetrics(request_id=request_id)
    
    try:
        async for chunk in response_data.body_iterator:
            metrics.bytes_received += len(chunk)
            try:
                decoded_chunk = utf8_decoder.decode(chunk, final=False)
                if not decoded_chunk:
                    metrics.unicode_errors += 1
                    continue
                metrics.chunks_processed += 1
                # ...
            except json.JSONDecodeError:
                metrics.json_errors += 1
                metrics.chunks_failed += 1
                # ...
    finally:
        metrics.finalize()
        logger.info(f"Stream metrics for {request_id}", extra=metrics.to_dict())
```

---

## 🧪 План тестирования

### Тест 1: UTF-8 стабильность
```bash
# Скрипт для генерации разных чанк-размеров
python test_unicode_streaming.py
```

```python
# test_unicode_streaming.py
import httpx
import asyncio

async def test_unicode_chunking():
    texts = [
        "Привет мир! 🌍",
        "Это тест с эмодзи 🚀🎉🔥",
        "日本語テスト",
        "مرحبا بالعالم"
    ]
    
    for text in texts:
        response = await httpx.post(
            "http://localhost:8777/v1/chat/completions",
            headers={"Authorization": "Bearer dummy"},
            json={
                "model": "deepseek/chat",
                "messages": [{"role": "user", "content": f"Повтори: {text}"}],
                "stream": True
            }
        )
        
        chunks = []
        async for chunk in response.aiter_bytes():
            chunks.append(chunk)
        
        print(f"Test '{text}': {len(chunks)} chunks, success: {response.status_code == 200}")
```

### Тест 2: Длинные ответы
```bash
curl -X POST http://localhost:8777/v1/chat/completions \
  -H "Authorization: Bearer dummy" \
  -d '{
    "model": "deepseek/chat",
    "messages": [{"role": "user", "content": "Напиши подробное эссе на 2000 слов о важности тестирования"}],
    "stream": true
  }' | wc -l  # Должно быть > 0 и без обрывов
```

### Тест 3: Стресс-тест
```python
# stress_test.py
import asyncio
import httpx

async def concurrent_requests(n=50):
    async with httpx.AsyncClient() as client:
        tasks = []
        for i in range(n):
            task = client.post(
                "http://localhost:8777/v1/chat/completions",
                headers={"Authorization": "Bearer dummy"},
                json={
                    "model": "deepseek/chat",
                    "messages": [{"role": "user", "content": f"Test {i}"}],
                    "stream": True
                },
                timeout=30.0
            )
            tasks.append(task)
        
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        success = sum(1 for r in responses if not isinstance(r, Exception))
        print(f"Success: {success}/{n}")

asyncio.run(concurrent_requests())
```

---

## 📊 Критерии успеха

### ✅ Этап 1 завершен если:
- [ ] Нет `UnicodeDecodeError` при любом языке/emoji
- [ ] Нет потерянных чанков из-за разрыва SSE/JSON
- [ ] Ошибки корректно передаются без `[DONE]`
- [ ] 100% тестов с мультиязычным контентом проходят

### ✅ Этап 2 завершен если:
- [ ] Автоматическое определение формата работает для всех провайдеров
- [ ] SSE комментарии и события обрабатываются корректно
- [ ] Нет таймаутов при нормальной работе
- [ ] Стресс-тест: 95%+ успешных запросов

### ✅ Этап 3 завершен если:
- [ ] Backpressure предотвращает OOM
- [ ] Метрики собираются для всех стримов
- [ ] Dashboard показывает статистику в реальном времени

---

## 🚀 Порядок развертывания

1. **Создать ветку:** `git checkout -b fix/streaming-stability`
2. **Реализовать Этап 1** (критические исправления)
3. **Тестирование Этапа 1:** Полный набор тестов
4. **Code Review + Merge в dev**
5. **Деплой в staging** с мониторингом
6. **Реализовать Этап 2** (стабильность)
7. **Тестирование + Review + Merge**
8. **Деплой в production** с постепенным rollout
9. **Этап 3** - по необходимости в отдельных PR

---

## 📝 Чеклист перед production

- [ ] Все тесты проходят (unit + integration)
- [ ] Code review пройден (минимум 2 ревьюера)
- [ ] Документация обновлена
- [ ] Метрики настроены
- [ ] Алерты настроены для ошибок стриминга
- [ ] Rollback план подготовлен
- [ ] Staging тестирование завершено
- [ ] Performance тесты пройдены
- [ ] Security аудит пройден (если нужно)

---

## 🔗 Связанные документы

- [AUDIT_REPORT.md](AUDIT_REPORT.md) - Детальный отчет об аудите
- [README.md](README.md) - Основная документация
- [TODO.md](TODO.md) - Текущие задачи

---

**Последнее обновление:** 2025-10-03  
**Статус:** Готов к реализации  
**Контакт:** @architect-mode