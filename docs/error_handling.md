# Обработка ошибок в LLM Router

## Обзор

В этом документе описывается система обработки ошибок в LLM Router, особенно в контексте стриминга ответов от провайдеров AI.

## Типы ошибок

### ProviderStreamError

Исключение `ProviderStreamError` выбрасывается при ошибках, связанных со стримингом ответов от AI провайдеров.

```python
from src.core.exceptions import ProviderStreamError

# Пример использования
try:
    async for chunk in stream_response:
        process_chunk(chunk)
except ProviderStreamError as e:
    logger.error(f"Ошибка стриминга: {e.message}, статус: {e.status_code}")
```

**Атрибуты:**
- `message`: Сообщение об ошибке
- `status_code`: HTTP статус код ошибки
- `error_code`: Код ошибки от провайдера

### ProviderNetworkError

Исключение `ProviderNetworkError` выбрасывается при сетевых ошибках при взаимодействии с AI провайдерами.

```python
from src.core.exceptions import ProviderNetworkError

try:
    response = await provider.make_request()
except ProviderNetworkError as e:
    logger.error(f"Сетевая ошибка: {e.message}")
    logger.debug(f"Исходное исключение: {e.original_exception}")
```

**Атрибуты:**
- `message`: Сообщение об ошибке
- `original_exception`: Исходное исключение

## Обработка ошибок 429 (Too Many Requests)

### Проблема

При работе с AI провайдерами часто возникает ошибка 429 "Too Many Requests". В контексте стриминга это может приводить к ошибке `ResponseNotRead`, так как ответ еще не был полностью прочитан.

### Решение

В базовом классе провайдера реализована система обработки ошибок 429 с автоматическими повторными попытками:

```python
@retry_on_rate_limit(max_retries=3, base_delay=1.0)
async def _stream_request(self, client, endpoint, request_body):
    # ... логика запроса
```

### Параметры повторных попыток

- `max_retries`: Максимальное количество повторных попыток (по умолчанию: 3)
- `base_delay`: Базовая задержка между попытками в секундах (по умолчанию: 1.0)
- `max_delay`: Максимальная задержка между попытками в секундах (по умолчанию: 60.0)
- `backoff_factor`: Коэффициент экспоненциального увеличения задержки (по умолчанию: 2.0)

### Логика повторных попыток

1. При получении ошибки 429 система ждет указанное время
2. Повторяет запрос с экспоненциально увеличивающейся задержкой
3. После максимального количества попыток выбрасывает исключение `ProviderStreamError`

## Обработка ошибки ResponseNotRead

### Проблема

Ошибка `ResponseNotRead` возникает при попытке доступа к содержимому ответа, которое еще не было прочитано. Это особенно актуально при работе с потоковыми ответами.

### Решение

Реализована безопасная обработка ответа:

```python
try:
    error_data = response.json()
except (ValueError, httpx.ResponseNotRead):
    # Если ответ еще не прочитан, используем текст
    error_data = {"error": {"message": response.text}}
```

## Рекомендации по обработке ошибок

### 1. Логирование ошибок

```python
import logging
from src.core.exceptions import ProviderStreamError, ProviderNetworkError

logger = logging.getLogger(__name__)

try:
    # ... код запроса
except ProviderStreamError as e:
    logger.warning(f"Ошибка стриминга от провайдера: {e.message}")
    # Можно добавить логику для уведомления администратора
except ProviderNetworkError as e:
    logger.error(f"Сетевая ошибка: {e.message}")
    # Можно добавить логику для переключения на другого провайдера
```

### 2. Обработка ошибок в пользовательском интерфейсе

```python
async def handle_streaming_request():
    try:
        async for chunk in streaming_generator():
            yield chunk
    except ProviderStreamError as e:
        yield {
            "type": "error",
            "code": e.error_code,
            "message": "Временная ошибка, попробуйте еще раз"
        }
```

### 3. Мониторинг ошибок

Рекомендуется отслеживать частоту ошибок 429 для каждого провайдера:

```python
# Пример мониторинга
error_metrics = {
    "provider_1_429": 0,
    "provider_2_429": 0
}

try:
    # ... запрос
except ProviderStreamError as e:
    if e.status_code == 429:
        error_metrics[f"{provider_name}_429"] += 1
```

## Тестирование

Для тестирования обработки ошибок используйте предоставленные тесты:

```bash
python -m pytest tests/unit/test_streaming_error_handling.py -v
```

## Дополнительные ресурсы

- [Документация по httpx](https://www.python-httpx.org/)
- [Документация по FastAPI](https://fastapi.tiangolo.com/)
- [Руководство по обработке ошибок в Python](https://docs.python.org/3/tutorial/errors.html)