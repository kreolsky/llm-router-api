# Анализ неудачных тестов

## Обзор

Из 106 тестов в папке `tests/api/`:
- **90 passed** (84.9%)
- **15 failed** (14.2%)
- **1 skipped** (0.9%)

Ниже приведен анализ причин неудачных тестов.

## Категории неудачных тестов

### 1. Тесты потоковой передачи (Streaming Tests)

**Неудачные тесты:**
- `test_streaming_chat_completion[local_orange]`
- `test_streaming_chat_completion[gemini_mini]`
- `test_streaming_chat_completion[deepseek_chat]`
- `test_streaming_chunk_structure[local_orange]`
- `test_streaming_chunk_structure[gemini_mini]`
- `test_streaming_chunk_structure[deepseek_chat]`
- `test_streaming_finish_reasons`
- `test_streaming_content_accumulation`

**Причина неудачи:**
Формат ответа потоковой передачи отличается от ожидаемого формата OpenAI API. Вместо стандартных полей `id`, `object`, `created`, `model`, `choices`, API возвращает метадические поля, такие как `completion_time`, `completion_tokens`, `completion_tokens_per_sec`, `prompt_time`.

**Пример ошибки:**
```
AssertionError: assert 'id' in {'completion_time': 1.39, 'completion_tokens': 39, 'completion_tokens_per_sec': 28.02, 'prompt_time': 0.12, ...}
```

**Рекомендация:**
Изменить формат ответа потоковой передачи, чтобы он соответствовал стандарту OpenAI API, или обновить тесты в соответствии с текущим форматом ответа.

### 2. Тесты обработки ошибок (Error Handling Tests)

**Неудачные тесты:**
- `test_chat_completion_missing_required_fields`
- `test_chat_completion_empty_messages`
- `test_create_embeddings_missing_required_fields`
- `test_create_embeddings_empty_input`
- `test_create_transcription_missing_required_fields`
- `test_create_transcription_empty_file`
- `test_create_transcription_large_file`

**Причина неудачи:**
API возвращает другие коды состояния HTTP, чем ожидалось в тестах.

**Примеры ошибок:**
1. Вместо `400 Bad Request` возвращается `422 Unprocessable Entity`:
   ```
   AssertionError: Should return error for missing messages
   assert 422 == 400
   ```

2. Вместо `400 Bad Request` возвращается `500 Internal Server Error`:
   ```
   AssertionError: Should return error for empty input
   assert 500 == 400
   ```

3. Вместо `400 Bad Request` или `413 Payload Too Large` возвращается `500 Internal Server Error`:
   ```
   AssertionError: assert 500 in [200, 400, 413]
   ```

**Рекомендация:**
Стандартизировать коды состояния HTTP для различных условий ошибок в соответствии с общепринятыми соглашениями:
- `400 Bad Request` для неверных запросов
- `422 Unprocessable Entity` для синтаксически правильных, но семантически неверных запросов
- `413 Payload Too Large` для слишком больших файлов
- Избегать `500 Internal Server Error` для предсказуемых ошибок ввода

## Детальный анализ ошибок

### 1. Ошибки потоковой передачи (8 тестов)

**Проблема:** Несоответствие формата ответа потоковой передачи ожиданиям тестов.

**Ожидаемый формат (OpenAI API):**
```json
{
  "id": "cmpl-xxxx",
  "object": "chat.completion.chunk",
  "created": 1234567890,
  "model": "model-id",
  "choices": [
    {
      "index": 0,
      "delta": {
        "role": "assistant",
        "content": "Hello"
      },
      "finish_reason": null
    }
  ]
}
```

**Фактический формат:**
```json
{
  "completion_time": 1.39,
  "completion_tokens": 39,
  "completion_tokens_per_sec": 28.02,
  "prompt_time": 0.12,
  "delta": {
    "content": "Hello"
  }
}
```

### 2. Ошибки обработки ошибок (7 тестов)

**Проблема:** Несоответствие кодов состояния HTTP ожиданиям тестов.

| Тест | Ожидаемый код | Фактический код | Описание |
|------|---------------|-----------------|----------|
| `test_chat_completion_missing_required_fields` | 400 | 422 | Отсутствуют обязательные поля |
| `test_chat_completion_empty_messages` | 400 | 200 | Пустые сообщения |
| `test_create_embeddings_missing_required_fields` | 400 | 422 | Отсутствуют обязательные поля |
| `test_create_embeddings_empty_input` | 400 | 500 | Пустой ввод |
| `test_create_transcription_missing_required_fields` | 400 | 500 | Отсутствуют обязательные поля |
| `test_create_transcription_empty_file` | 400 | 500 | Пустой файл |
| `test_create_transcription_large_file` | [200, 400, 413] | 500 | Большой файл |

## Рекомендации для разработчиков

### 1. Стандартизация формата ответа потоковой передачи

Измените формат ответа потоковой передачи, чтобы он соответствовал стандарту OpenAI API, или предоставьте опцию для выбора формата ответа.

### 2. Стандартизация кодов состояния HTTP

Обновите коды состояния HTTP для различных условий ошибок:

| Условие ошибки | Рекомендуемый код |
|----------------|-------------------|
| Отсутствуют обязательные поля | 400 Bad Request |
| Неверный формат данных | 422 Unprocessable Entity |
| Пустые сообщения/ввод | 400 Bad Request |
| Пустой файл | 400 Bad Request |
| Слишком большой файл | 413 Payload Too Large |
| Внутренняя ошибка сервера | 500 Internal Server Error |

### 3. Улучшение обработки ошибок

Добавьте более подробные сообщения об ошибках в теле ответа, чтобы помочь клиентам понять причину ошибки.

## Заключение

Большинство тестов (84.9%) проходят успешно, что указывает на хорошую общую функциональность API. Основные проблемы связаны с форматом ответа потоковой передачи и обработкой ошибок. Эти проблемы можно решить, стандартизировав форматы ответов и коды состояния HTTP в соответствии с общепринятыми практиками.