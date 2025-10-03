# 🚀 Быстрый старт: Исправление проблем стриминга

## 📌 TL;DR

**Проблема:** Стрим обрывается при длинных ответах в OpenWebUI  
**Причина:** Разрыв многобайтных UTF-8 символов и SSE событий между HTTP чанками  
**Решение:** 3 критических исправления (~6-8 часов работы)

---

## 🔴 Что сломано (критично)

### 1. Разрыв UTF-8 символов между чанками
```python
# ❌ ТЕКУЩИЙ КОД (строка 163)
decoded_chunk = chunk.decode('utf-8')  # Падает на emoji/кириллице

# ✅ ИСПРАВЛЕНИЕ
utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='ignore')
decoded_chunk = utf8_decoder.decode(chunk, final=False)
```

**Почему это критично:**
- Работает только с английским текстом
- Русский текст → случайные обрывы
- Emoji → гарантированные ошибки
- OpenWebUI + мультиязычные модели → нестабильно

---

### 2. Нет буферизации для неполных SSE/JSON строк
```python
# ❌ ТЕКУЩИЙ КОД
if decoded_chunk.startswith('data: '):
    # Что если 'data: ' разорвано между чанками?

# ✅ ИСПРАВЛЕНИЕ
sse_buffer += decoded_chunk
while '\n\n' in sse_buffer:
    event, sse_buffer = sse_buffer.split('\n\n', 1)
    # Обработать полное SSE событие
```

**Почему это критично:**
- Малые чанки от медленных провайдеров → обрывы
- Длинные ответы → больше чанков → выше вероятность разрыва

---

### 3. Некорректная обработка ошибок
```python
# ❌ ТЕКУЩИЙ КОД
except JSONDecodeError:
    yield error
    break
# ... позже
yield b"data: [DONE]\n\n"  # Отправляется даже после ошибки!

# ✅ ИСПРАВЛЕНИЕ
stream_has_error = False
except JSONDecodeError:
    yield error
    stream_has_error = True
    break

if not stream_has_error:
    yield b"data: [DONE]\n\n"
```

---

## ⚡ Быстрое исправление (30 минут)

Минимальный патч для стабилизации:

```python
# В src/services/chat_service.py, метод _stream_response_handler

import codecs

async def _stream_response_handler(self, response_data, provider_type, requested_model, request_id, user_id):
    full_content = ""
    stream_completed_usage = None
    
    # ✅ 1. Добавить UTF-8 декодер
    utf8_decoder = codecs.getincrementaldecoder('utf-8')(errors='ignore')
    
    # ✅ 2. Добавить буферы
    sse_buffer = ""
    stream_has_error = False
    
    try:
        async for chunk in response_data.body_iterator:
            try:
                # ✅ 3. Использовать инкрементальный декодер
                decoded_chunk = utf8_decoder.decode(chunk, final=False)
                if not decoded_chunk:
                    continue
                
                # ✅ 4. Буферизация SSE
                sse_buffer += decoded_chunk
                while '\n\n' in sse_buffer:
                    event, sse_buffer = sse_buffer.split('\n\n', 1)
                    if event.strip():
                        full_content, stream_completed_usage = self._process_openai_sse_event(
                            event, full_content, stream_completed_usage, request_id, user_id
                        )
                        yield f"{event}\n\n".encode('utf-8')
                        
            except Exception as e:
                logger.error(f"Error in stream: {e}")
                yield self._format_sse_error(str(e), "stream_error", 500)
                stream_has_error = True
                break
    
    except Exception as e:
        logger.error(f"Critical stream error: {e}")
        stream_has_error = True
    
    # ✅ 5. Обработать остаток буфера
    if sse_buffer.strip() and not stream_has_error:
        full_content, stream_completed_usage = self._process_openai_sse_event(
            sse_buffer, full_content, stream_completed_usage, request_id, user_id
        )
    
    # ✅ 6. [DONE] только если нет ошибок
    if not stream_has_error:
        self._log_streaming_completion(request_id, user_id, requested_model, full_content, stream_completed_usage)
        yield b"data: [DONE]\n\n"
```

---

## 🧪 Как проверить

### Тест 1: UTF-8 стабильность
```bash
curl -X POST http://localhost:8777/v1/chat/completions \
  -H "Authorization: Bearer dummy" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek/chat",
    "messages": [
      {"role": "user", "content": "Ответь на русском языке с эмодзи: расскажи про программирование 🚀💻🔥"}
    ],
    "stream": true
  }'
```

**Ожидание:** Полный ответ без обрывов, все emoji отображаются корректно

### Тест 2: Длинный ответ
```bash
curl -X POST http://localhost:8777/v1/chat/completions \
  -H "Authorization: Bearer dummy" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek/chat",
    "messages": [
      {"role": "user", "content": "Напиши подробное эссе на 1500 слов о важности тестирования"}
    ],
    "stream": true
  }' | tee response.txt
```

**Ожидание:** Весь текст получен, файл заканчивается на `data: [DONE]`

### Тест 3: OpenWebUI интеграция
1. Запустить OpenWebUI
2. Настроить подключение к роутеру
3. Отправить запрос с просьбой ответить на русском с emoji
4. Проверить что ответ полностью отображается

---

## 📂 Файлы для изменения

### Критичные (обязательно):
- ✅ [`src/services/chat_service.py`](src/services/chat_service.py) - основные исправления
  - Метод `_stream_response_handler` (строка 156)
  - Метод `_process_openai_sse_chunk` → переименовать в `_process_openai_sse_event`
  - Метод `_format_sse_error` (строка 288)

### Важные (рекомендуется):
- ⚠️ [`src/providers/base.py`](src/providers/base.py) - таймауты (строка 27)
- ⚠️ [`src/providers/openai.py`](src/providers/openai.py) - таймауты (строка 23)

### Дополнительные (опционально):
- 📝 Добавить метрики стриминга
- 📝 Добавить backpressure механизм

---

## 🎯 Приоритеты

### Сейчас (критично):
1. ✅ UTF-8 incremental decoder
2. ✅ SSE буферизация
3. ✅ Исправить error handling

### Скоро (важно):
4. ⚠️ Настроить таймауты
5. ⚠️ Автоопределение формата стрима
6. ⚠️ Полная SSE валидация

### Потом (улучшения):
7. 📝 Backpressure
8. 📝 Метрики и мониторинг
9. 📝 Performance оптимизации

---

## 📚 Дополнительная документация

- 📋 [AUDIT_REPORT.md](AUDIT_REPORT.md) - Полный отчет аудита с деталями
- 🚀 [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) - Пошаговый план реализации
- 📖 [README.md](README.md) - Документация проекта

---

## 🤝 Следующие шаги

### Вариант 1: Быстрое исправление
```bash
# Переключиться в режим Code
# Применить минимальный патч выше
# Протестировать
# Задеплоить
```

### Вариант 2: Полное исправление
```bash
# Следовать плану из IMPLEMENTATION_PLAN.md
# Этап 1: Критические исправления (6-8 часов)
# Этап 2: Улучшение стабильности (4-6 часов)
# Этап 3: Архитектурные улучшения (опционально)
```

---

## ❓ FAQ

**Q: Почему это не ловилось раньше?**  
A: Работало с английскими моделями. Русский текст и emoji выявили проблему.

**Q: Это затронет все провайдеры?**  
A: Да, проблема в общем коде обработки стримов.

**Q: Можно ли исправить по частям?**  
A: Можно, но все 3 проблемы связаны. Лучше исправить разом.

**Q: Как долго займет исправление?**  
A: Минимальный патч - 30 мин. Полное решение - 6-8 часов.

**Q: Есть ли риски?**  
A: Минимальные. Изменения локальные, не трогают API контракт.

---

**Готовы начать?** Переключитесь в режим Code для реализации исправлений! 🚀