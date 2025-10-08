# Реализация санитизации сообщений для удаления клиентской контаминации

## Проблема

Из обновленного лога видно, что клиент отправляет сообщения с полем `"done": false` (строка 4 в логе), которое достигает OpenRouter и вызывает 400 Bad Request:

```json
{
  "role": "assistant",
  "content": "",
  "done": false
}
```

## Решение

Нужно реализовать санитизацию сообщений на уровне провайдера OpenAI, чтобы удалить клиентские поля перед отправкой в OpenRouter.

## Детальная реализация

### Шаг 1: Добавление метода санитизации в OpenAI провайдер

В файле `src/providers/openai.py` добавить метод:

```python
def _sanitize_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Удаляем только служебные поля, сохраняя все остальные
    
    Args:
        messages: Список сообщений для очистки
        
    Returns:
        Очищенный список сообщений
    """
    sanitized = []
    for message in messages:
        clean_message = message.copy()  # Копируем всё сообщение
        
        # Удаляем только известные служебные поля
        service_fields = ['done', '__stream_end__', '__internal__']
        for field in service_fields:
            clean_message.pop(field, None)
        
        sanitized.append(clean_message)
    return sanitized
```

### Шаг 2: Интеграция санитизации в метод `chat_completions`

В методе `chat_completions` перед отправкой запроса:

```python
async def chat_completions(self, request_body: Dict[str, Any], provider_model_name: str, model_config: Dict[str, Any]) -> Any:
    # Transform request: Replace the model name with the provider's specific model name
    request_body["model"] = provider_model_name
    
    # Merge options from model_config into the request_body
    options = model_config.get("options")
    if options:
        request_body = deep_merge(request_body, options)
    
    # SANITIZE MESSAGES: Remove client-side contamination
    if "messages" in request_body:
        request_body["messages"] = self._sanitize_messages(request_body["messages"])
    
    # Rest of the existing code...
```

### Шаг 3: Обновление DEBUG логирования

После санитизации добавить логирование для отладки:

```python
# DEBUG логирование очищенного запроса к провайдеру
if logger.isEnabledFor(logging.DEBUG):
    debug_request = {
        "url": f"{self.base_url}/chat/completions",
        "headers": self.headers,
        "request_body": request_body,  # Теперь очищенный
        "provider_model_name": provider_model_name,
        "model_config": model_config
    }
    logger.debug(
        "DEBUG: OpenAI Chat Request (Sanitized)",
        extra={
            "debug_json_data": debug_request,
            "debug_data_flow": "to_provider",
            "debug_component": "openai_provider"
        }
    )
```

## Преимущества этого подхода

1. **Точечное решение**: Удаляем только известные служебные поля
2. **Сохранение совместимости**: Все остальные поля остаются unchanged
3. **Защита от будущих проблем**: Даже если клиент добавит другие служебные поля, они будут удалены
4. **Минимальные изменения**: Только одна точка входа в провайдер

## Тестирование

Создать тест для проверки санитизации:

```python
def test_message_sanitization():
    """Тест очистки сообщений от клиентской контаминации"""
    contaminated_messages = [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "", "done": false}
    ]
    
    provider = OpenAICompatibleProvider(config={["base_url": "https://api.openai.com/v1"]}, client=None)
    sanitized = provider._sanitize_messages(contaminated_messages)
    
    # Проверяем, что поле 'done' удалено
    assert "done" not in sanitized[2]
    # Проверяем, что остальные поля сохранены
    assert sanitized[2]["role"] == "assistant"
    assert sanitized[2]["content"] == ""
```

## Ожидаемый результат

После реализации этого решения:

1. Клиент может отправлять сообщения с полями `"done": false/true`
2. Провайдер OpenAI очистит эти поля перед отправкой в OpenRouter
3. OpenRouter получит только валидные поля OpenAI API
4. 400 Bad Request ошибки исчезнут

## Альтернативные подходы

Если это решение не сработает, можно рассмотреть:

1. **Санитизация на уровне middleware**: Очищать сообщения раньше вpipeline
2. **Санитизация в chat_service**: Очищать перед передачей провайдеру
3. **Валидация на входе**: Отклонять запросы с нестандартными полями

Но санитизация на уровне провайдера - наиболее точечное и безопасное решение.